Pull Request Review Caveats
===========================

While the PR review feature has been thoroughly tested, there are still some caveats to beware of when using PR reviews.

.. _repository settings: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository#preventing-github-actions-from-creating-or-approving-pull-requests
.. _organization settings: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository#preventing-github-actions-from-creating-or-approving-pull-requests

1. The "GitHub Actions" bot may need to be allowed to approve PRs; see github docs for
   `repository settings`_ or `organization settings`_ about adjust the required permissions for this.
   By default, the bot cannot approve PR changes, only request more changes.
   This will show as a logged warning if the given token (env var ``GITHUB_TOKEN``) isn't configured with
   the proper permissions.
2. The feature is auto-disabled for

   - closed PRs
   - PRs marked as "draft"
   - push events
3. Clang-tidy and clang-format suggestions are shown in 1 PR review.

   - Users are encouraged to choose either ``tidy-review`` or ``format-review``.
     Enabling both will likely show duplicate or similar suggestions.
     Remember, clang-tidy can be configured to use the same ``style`` that clang-format accepts.
     There is no current implementation to combine suggestions from both tools (clang-tidy kind of
     does that anyway).
   - Each generated review is specific to the commit that triggered the CI.
   - Outdated reviews are dismissed but not marked as resolved.
     Also, the outdated review's summary comment is not automatically hidden.
     To reduce PR thread noise, users interaction is required.
     GitHub REST API does not provide a way to hide comments or mark review suggestions as resolved.

     .. note::

        We do support an environment variable named ``CPP_LINTER_PR_REVIEW_SUMMARY_ONLY``.
        If the variable is set to ``true``, then the review only contains a summary comment
        with no suggestions posted in the diff.
4. If any suggestions did not fit within the PR diff, then the review's summary comment will
   indicate how many suggestions were left out.
   The full patch of suggestions is always included as a collapsed code block in the review summary
   comment. This isn't a problem we can fix.
   GitHub won't allow review comments/suggestions to target lines that are not shown in the PR diff.

   - Users are encouraged to set ``lines-changed-only`` to ``true``.
     This will *help* us keep the suggestions limited to lines that are shown within the PR diff.
     However, there are still some cases where clang-format or clang-tidy will apply fixes to lines
     that are not within the diff.
     This can't be avoided because the ``--line-filter`` passed to the clang-tidy (and ``--lines``
     passed to clang-format) only applies to analysis, not fixes.
   - Not every diagnostic from clang-tidy can be automatically fixed.
     Some diagnostics require user interaction/decision to properly address.
   - Some fixes provided might depend on what compiler is used.
     We have made it so clang-tidy takes advantage of any fixes provided by the compiler.
     Compilation errors may still prevent clang-tidy from reporting all concerns.
