# For details, run:
#   nu .github/workflows/tag-release.nu -h

# Run an external command and output its elapsed time.
#
# Not useful if you need to capture the command's output.
export def --wrapped run-cmd [...cmd: string] {
    let app = if (
        ($cmd | first) == "git"
        or ($cmd | first) == "gh"
    ) {
        ($cmd | first 2) | str join " "
    } else if ($cmd | first) == 'uvx' {
        $cmd | skip 1 | first
    } else {
        ($cmd | first)
    }
    print $"(ansi blue)\nRunning(ansi reset) ($cmd | str join ' ')"
    let elapsed = timeit {|| ^($cmd | first) ...($cmd | skip 1)}
    print $"(ansi magenta)($app) took ($elapsed)(ansi reset)"
}

# Is this executed in a CI run?
#
# Uses env var CI to determine the resulting boolean
export def is-in-ci [] {
    $env | get --optional CI | default 'false' | (($in == 'true') or ($in == true))
}

# Is the the default branch currently checked out?
#
# Only accurate if the default branch is named "main".
export def is-on-main [] {
    let branch = (
        ^git branch
        | lines
        | where {$in | str starts-with '*'}
        | first
        | str trim --left --char '*'
        | str trim
    ) == 'main'
    $branch
}

# Parse the given `ver` into integer components.
#
# Returns a record<major: int, minor: int, patch: int>.
def "version parse" [
    ver: string, # The fully qualified semver string
] {
    (
        $ver
        | str trim --left --char "v"
        | parse "{major}.{minor}.{patch}"
        | first
        | into int "major" "minor" "patch"
    )
}

# Join the given `ver` record's fields into a fully qualified semver string.
def "version join" [
    ver: record<major: int, minor: int, patch: int>, # The record of version components.
] {
    $ver | format pattern "v{major}.{minor}.{patch}"
}

# Get the next version for a new release.
#
# Uses `git-cliff` if `component` is set to `auto`.
export def get-next-version [
    component: string, # The version component. Must be one of [auto, major, minor, patch]
    cliff_config?: string, # The path to git-cliff config (cliff.toml)
] {
    if ($component == 'auto') {
        print "Determining version automatically"
        mut args = [--bumped-version]
        if ($cliff_config | is-not-empty) {
            $args = $args | append [--config $cliff_config]
        }
        let next = (^uvx git-cliff ...$args) | str trim | version parse $in
        print $"Result:"
        print $next
        version join $next
    } else {
        let git_out = (
            (^git describe --tags --abbrev=0)
            | complete
            | (
                if ($in.exit_code != 0) {
                    "v0.0.0"
                } else {
                    $in.stdout
                }
            )
        )
        let current_tag = $git_out | str trim | version parse $in
        print $"Manually bumping the `($component)` version of:"
        print $current_tag
        mut new_tag = $current_tag
        match $component {
            "major" => {
                $new_tag.major = $current_tag.major + 1
                $new_tag.minor = 0
                $new_tag.patch = 0
            }
            "minor" => {
                $new_tag.minor = $current_tag.minor + 1
                $new_tag.patch = 0
            }
            "patch" => {$new_tag.patch = $current_tag.patch + 1}
            _ => {
                error make {
                    msg: $"'($component)' is not a supported value: [auto, major, minor, patch]"
                }
            }
        }
        print "Result:"
        print $new_tag
        version join $new_tag
    }
}

# Move applicable rolling tags to the checked out HEAD.
#
# For example, `v1` is moved to the newer `v1.2.3` ref.
#
# This does nothing if no tags match the major version
def mv-rolling-tag [
    ver: string # The fully qualified version of the new tag.
] {
    let tag = version parse $ver
    let major_tag = $"v($tag | get major)"
    print $"Moving any tags named '($major_tag)'"
    let tags = (^git tag --list) | lines | each {$in | str trim}
    if ($major_tag in $tags) {
        # delete local tag
        run-cmd git tag -d $major_tag
        # delete remote tag
        run-cmd git push origin $":refs/tags/($major_tag)"

        # create new tag
        run-cmd git tag $major_tag
        run-cmd git push origin $major_tag
        print $"Adjusted tag ($major_tag)"
    }
}

# Find the repo's first commit's SHA.
#
# This is needed for git-cliff to correctly hyperlink the diff
# between the first commit and the first release.
export def find-first-commit [] {
    (^git rev-list --max-parents=0 HEAD) | str trim
}

# Get repo name.
#
# First tries to read from env var `GITHUB_REPO`
# Defaults to parsing the working directory's `origin` remote url.
export def find-repo-name [] {
    $env | get --optional "GITHUB_REPO" | default {
        let origin = (^git remote get-url origin) | str trim
        (
            if (not ($origin | str starts-with "https://")) {
                let patched_ssh = $origin | str replace --regex '([^:]):' '$1:/'
                $"ssh://($patched_ssh)"
            } else {
                $origin
            }
        )
        | url parse
        | get path
        | str trim --left --char "/"
        | path parse
        | format pattern "{parent}/{stem}"
    }
}

# Find a cliff.toml to pass to git-cliff
#
# Relies on `GIT_CLIFF_CONFIG` present in env.
# Otherwise, tries to find it in `.github/cliff.toml`
export def find-cliff-toml [] {
    if ($env | get --optional "GIT_CLIFF_CONFIG" | is-not-empty) {
        print $"(ansi green)GIT_CLIFF_CONFIG found in env: ($env.GIT_CLIFF_CONFIG)(ansi reset)"
        null
    } else {
        print $"(ansi yellow)Path to git-cliff config \(cliff.toml) is not set via GIT_CLIFF_CONFIG(ansi reset)"
        let guess = ".github/cliff.toml"
        if ($guess | path exists) {
            print $"(ansi yellow)Attempting to use ($guess) instead.(ansi reset)"
            $guess
        } else {
            print $"(ansi red)No git-cliff config found; git-cliff will use its default behavior.(ansi reset)"
            null
        }
    }
}

const CHANGELOG = "CHANGELOG.md"
export const RELEASE_NOTES = $nu.temp-dir | path join "ReleaseNotes.md"

# Use git-cliff to generate list of changes.
def gen-changes [
    ver: string, # The new version to release
    first_commit: string, # The SHA of the first commit for this repo.
    gh_repo: string, # The name of the remote repo from which to fetch changes.
    cliff_config?: string, # The path to git-cliff config (cliff.toml)
    --full, # If given, generate entire CHANGELOG.md. Otherwise, generate just release notes.
] {
    mut args = [--tag $ver]
    if ($cliff_config | is-not-empty) {
        $args = $args | append [--config $cliff_config]
    }
    if $full {
        print $"\nRegenerating the ($CHANGELOG)"
        $args = $args | append [--output $CHANGELOG]
    } else {
        print "\nGenerating Release Notes"
        $args = $args | append [
            --output $RELEASE_NOTES --unreleased --strip header
        ]
    }

    # make an immutable shadow of the mutable variable
    let args = $args
    with-env {FIRST_COMMIT: $first_commit, GITHUB_REPO: $gh_repo} {
        # cannot use mutable variables in this block (a closure)
        run-cmd uvx git-cliff ...$args
    }
}

# A script that will
#
# 1. Generate Release notes (from unreleased changes).
# 2. (Re)generate the CHANGELOG.md in repo root and push any changes
# 3. Create a GitHub release, which in turn creates a git tag on the default branch
# 4. Move any major tags (eg. `v2`) that correspond with the new release's tag.
#    This step does nothing if no major tag exists.
#
# This script is designed to be run in CI or locally.
# Either way, this script will abort if the current branch is not 'main'.
#
# The following tools are used and must be installed:
#
# - git (https://git-scm.com/)
# - uv (https://docs.astral.sh/uv/) used to install/run git-cliff.
#   See .github/requirements.txt for the pinned version of git-cliff.
# - gh-cli (https://cli.github.com/)
#
# Supported `component` parameter values are:
#
# - `auto` (relies on `git-cliff` to determine the next version)
# - `patch`
# - `minor`
# - `major`
#
# If no `component` is given, then `auto` is used.
def main [
    component?: string, # The version component to bump.
] {
    let gh_repo = find-repo-name
    print $"GH_REPO: ($gh_repo)"

    if ($gh_repo | str ends-with ".github") {
        error make {
            msg: "The org repo is not intended for deployment; aborting"
        }
    }

    let first_commit = find-first-commit
    print $"First commit is ($first_commit)"

    let is_ci = is-in-ci

    if ($env | get --optional "GITHUB_TOKEN" | is-empty) {
        let problem = "No GITHUB_TOKEN set via env var."
        let effect = "git-cliff output will not conform to expected behavior"
        if $is_ci {
            error make {
                msg: $"($problem) ($effect)"
            }
        } else {
            print $"(ansi yellow)($problem) (ansi red)($effect)(ansi reset)"
        }
    }

    # ensure cliff.toml is provided to git-cliff
    let cliff_config = find-cliff-toml

    let component = if $component in [auto patch minor major] {
        $component
    } else {
        if ($component | is-not-empty) {
            let prompt = $"The component value ($component) is not supported; using `auto` instead."
            if $is_ci {
                print $"::notice::($prompt)"
            } else {
                print $prompt
            }
        }
        "auto"
    }
    let ver = get-next-version $component $cliff_config

    if not (is-on-main) {
        error make {
            msg: "The default branch is not checked out; aborting"
        }
    }

    gen-changes $ver $first_commit $gh_repo $cliff_config --full

    # push changes (if any)
    run-cmd git add --all
    let has_changes = (^git status -s) | lines | is-not-empty
    if $has_changes {
        if $is_ci {
            run-cmd git config --global user.name $"($env.GITHUB_ACTOR)"
            run-cmd git config --global user.email $"($env.GITHUB_ACTOR_ID)+($env.GITHUB_ACTOR)@users.noreply.github.com"
        }
        run-cmd git commit -m $"build: bump version to ($ver)"
        run-cmd git push
        # HEAD is now moved
    }

    gen-changes $ver $first_commit $gh_repo $cliff_config
    # push the new tag (pointing at HEAD) by creating a GitHub release
    print $"Deploying ($ver)"
    run-cmd ...[
        gh
        release
        create
        $ver
        --title
        $ver
        --notes-file
        $RELEASE_NOTES
        --repo
        $gh_repo
    ]

    # now move rolling tags if they are present
    mv-rolling-tag $ver
}
