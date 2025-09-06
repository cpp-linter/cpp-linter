# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
<!-- markdownlint-disable MD024 -->

## [1.10.7] - 2025-03-26

### <!-- 1 --> 🚀 New features and improvements

- Update Python support versions by \@shenxianpeng in [#134](https://github.com/cpp-linter/cpp-linter/pull/134)
- Add clang-tools v19 to dev tests by \@shenxianpeng in [#138](https://github.com/cpp-linter/cpp-linter/pull/138)
- Replace deprecated classifier with licence expression (PEP 639) by \@shenxianpeng in [#136](https://github.com/cpp-linter/cpp-linter/pull/136)

[1.10.7]: https://github.com/cpp-linter/cpp-linter/compare/v1.10.6...v1.10.7

Full commit diff: [`v1.10.6...v1.10.7`][1.10.7]

## [1.10.6] - 2024-12-12

### <!-- 1 --> 🚀 New features and improvements

- File IO timeout API by \@2bndy5 in [#133](https://github.com/cpp-linter/cpp-linter/pull/133)

[1.10.6]: https://github.com/cpp-linter/cpp-linter/compare/v1.10.5...v1.10.6

Full commit diff: [`v1.10.5...v1.10.6`][1.10.6]

## [1.10.5] - 2024-12-07

### <!-- 1 --> 🚀 New features and improvements

- Prefix every review comment by \@2bndy5 in [#132](https://github.com/cpp-linter/cpp-linter/pull/132)

[1.10.5]: https://github.com/cpp-linter/cpp-linter/compare/v1.10.4...v1.10.5

Full commit diff: [`v1.10.4...v1.10.5`][1.10.5]

## [1.10.4] - 2024-10-18

### <!-- 1 --> 🚀 New features and improvements

- Enhance parsing paginated diffs by \@2bndy5 in [#125](https://github.com/cpp-linter/cpp-linter/pull/125)

[1.10.4]: https://github.com/cpp-linter/cpp-linter/compare/v1.10.3...v1.10.4

Full commit diff: [`v1.10.3...v1.10.4`][1.10.4]

## [1.10.3] - 2024-10-05

### <!-- 1 --> 🚀 New features and improvements

- Capture and output clang version used in feedback by \@2bndy5 in [#124](https://github.com/cpp-linter/cpp-linter/pull/124)

[1.10.3]: https://github.com/cpp-linter/cpp-linter/compare/v1.10.2...v1.10.3

Full commit diff: [`v1.10.2...v1.10.3`][1.10.3]

## [1.10.2] - 2024-09-20

### <!-- 4 --> 🐛 Bug fixes

- Swap file names in paginated changed files's diff by \@2bndy5 in [#121](https://github.com/cpp-linter/cpp-linter/pull/121)

[1.10.2]: https://github.com/cpp-linter/cpp-linter/compare/v1.10.1...v1.10.2

Full commit diff: [`v1.10.1...v1.10.2`][1.10.2]

## [1.10.1] - 2024-09-09

### <!-- 1 --> 🚀 New features and improvements

- Improve creating patch for PR review suggestions by \@2bndy5 in [#111](https://github.com/cpp-linter/cpp-linter/pull/111)
- Pass style to clang-tidy by \@2bndy5 in [#114](https://github.com/cpp-linter/cpp-linter/pull/114)
- Resort to paginated request(s) to get file changes by \@2bndy5 in [#116](https://github.com/cpp-linter/cpp-linter/pull/116)
- Refactor creating PR review comments by \@2bndy5 in [#117](https://github.com/cpp-linter/cpp-linter/pull/117)

### <!-- 4 --> 🐛 Bug fixes

- Fix clang-analyzer diagnostic's bad hyperlinks by \@2bndy5 in [#119](https://github.com/cpp-linter/cpp-linter/pull/119)

[1.10.1]: https://github.com/cpp-linter/cpp-linter/compare/v1.10.0...v1.10.1

Full commit diff: [`v1.10.0...v1.10.1`][1.10.1]

## [1.10.0] - 2024-06-07

### <!-- 1 --> 🚀 New features and improvements

- Allow PR reviews to be passive by \@2bndy5 in [#107](https://github.com/cpp-linter/cpp-linter/pull/107)

[1.10.0]: https://github.com/cpp-linter/cpp-linter/compare/v1.9.2...v1.10.0

Full commit diff: [`v1.9.2...v1.10.0`][1.10.0]

## [1.9.2] - 2024-06-01

### <!-- 4 --> 🐛 Bug fixes

- Fix test affected by #108 by \@2bndy5 in [#109](https://github.com/cpp-linter/cpp-linter/pull/109)

[1.9.2]: https://github.com/cpp-linter/cpp-linter/compare/v1.9.1...v1.9.2

Full commit diff: [`v1.9.1...v1.9.2`][1.9.2]

## [1.9.1] - 2024-05-09

### <!-- 4 --> 🐛 Bug fixes

- prevent dead links (to tidy diagnostics pages) in thread comments & step summaries by \@2bndy5 in [#106](https://github.com/cpp-linter/cpp-linter/pull/106)

[1.9.1]: https://github.com/cpp-linter/cpp-linter/compare/v1.9.0...v1.9.1

Full commit diff: [`v1.9.0...v1.9.1`][1.9.1]

## [1.9.0] - 2024-05-06

### <!-- 1 --> 🚀 New features and improvements

- Swtich to actions/stale by \@shenxianpeng in [#102](https://github.com/cpp-linter/cpp-linter/pull/102)
- Abstract `api_request()` with custom rate-limit headers by \@2bndy5 in [#104](https://github.com/cpp-linter/cpp-linter/pull/104)
- Glob ignores by \@2bndy5 in [#103](https://github.com/cpp-linter/cpp-linter/pull/103)

### <!-- 9 --> 📝 Documentation

- More doc updates by \@2bndy5 in [#100](https://github.com/cpp-linter/cpp-linter/pull/100)

[1.9.0]: https://github.com/cpp-linter/cpp-linter/compare/v1.8.1...v1.9.0

Full commit diff: [`v1.8.1...v1.9.0`][1.9.0]

## [1.8.1] - 2024-03-27

### <!-- 4 --> 🐛 Bug fixes

- Ensure stdout is flushed, not buffered by \@2bndy5 in [#98](https://github.com/cpp-linter/cpp-linter/pull/98)

### <!-- 9 --> 📝 Documentation

- Inline badges in README.rst by \@2bndy5 in [#96](https://github.com/cpp-linter/cpp-linter/pull/96)
- Minor updates to docs by \@2bndy5 in [#99](https://github.com/cpp-linter/cpp-linter/pull/99)

[1.8.1]: https://github.com/cpp-linter/cpp-linter/compare/v1.8.0...v1.8.1

Full commit diff: [`v1.8.0...v1.8.1`][1.8.1]

## [1.8.0] - 2024-03-26

### <!-- 1 --> 🚀 New features and improvements

- Enable parallelism by \@jnooree in [#92](https://github.com/cpp-linter/cpp-linter/pull/92)
- Use io.StringIO instead tempdir/tempfile by \@jnooree in [#94](https://github.com/cpp-linter/cpp-linter/pull/94)

### <!-- 4 --> 🐛 Bug fixes

- Fix autolabeler by adding labeler.yml action by \@shenxianpeng in [#87](https://github.com/cpp-linter/cpp-linter/pull/87)
- Conditionally create comment by \@2bndy5 in [#91](https://github.com/cpp-linter/cpp-linter/pull/91)

### <!-- 6 --> 📦 Dependency updates

- update dependabot.yml to bump group updates by \@shenxianpeng in [#88](https://github.com/cpp-linter/cpp-linter/pull/88)

[1.8.0]: https://github.com/cpp-linter/cpp-linter/compare/v1.7.4...v1.8.0

Full commit diff: [`v1.7.4...v1.8.0`][1.8.0]

## New Contributors

- @jnooree made their first contribution in [#94](https://github.com/cpp-linter/cpp-linter/pull/94)

## [1.7.4] - 2024-03-05

### <!-- 1 --> 🚀 New features and improvements

- Create codeql.yml to support codeql analysis by \@shenxianpeng in [#86](https://github.com/cpp-linter/cpp-linter/pull/86)
- Handle REST API rate limits and pagination by \@2bndy5 in [#80](https://github.com/cpp-linter/cpp-linter/pull/80)

### <!-- 9 --> 📝 Documentation

- Add permissions doc and RTD config by \@2bndy5 in [#83](https://github.com/cpp-linter/cpp-linter/pull/83)
- Revise CLI doc generation by \@2bndy5 in [#85](https://github.com/cpp-linter/cpp-linter/pull/85)

[1.7.4]: https://github.com/cpp-linter/cpp-linter/compare/v1.7.3...v1.7.4

Full commit diff: [`v1.7.3...v1.7.4`][1.7.4]

## [1.7.3] - 2024-02-25

### <!-- 1 --> 🚀 New features and improvements

- Switch to reusable workflows by \@shenxianpeng in [#79](https://github.com/cpp-linter/cpp-linter/pull/79)
- Re-enable thread-comments on private repos by \@2bndy5 in [#81](https://github.com/cpp-linter/cpp-linter/pull/81)

[1.7.3]: https://github.com/cpp-linter/cpp-linter/compare/v1.7.2...v1.7.3

Full commit diff: [`v1.7.2...v1.7.3`][1.7.3]

## [1.7.2] - 2024-02-18

### <!-- 1 --> 🚀 New features and improvements

- Apply no-lgtm to PR reviews by \@2bndy5 in [#78](https://github.com/cpp-linter/cpp-linter/pull/78)

[1.7.2]: https://github.com/cpp-linter/cpp-linter/compare/v1.7.1...v1.7.2

Full commit diff: [`v1.7.1...v1.7.2`][1.7.2]

## [1.7.1] - 2024-02-13

### <!-- 4 --> 🐛 Bug fixes

- Account for clang-tidy notes without fixes in PR reviews by \@2bndy5 in [#76](https://github.com/cpp-linter/cpp-linter/pull/76)

[1.7.1]: https://github.com/cpp-linter/cpp-linter/compare/v1.7.0...v1.7.1

Full commit diff: [`v1.7.0...v1.7.1`][1.7.1]

## [1.7.0] - 2024-02-12

### <!-- 1 --> 🚀 New features and improvements

- Make verbosity disabled by default by \@2bndy5 in [#47](https://github.com/cpp-linter/cpp-linter/pull/47)
- Complete refactor by \@2bndy5 in [#49](https://github.com/cpp-linter/cpp-linter/pull/49)
- Link clang-tidy diagnostic names to clang-tidy docs by \@2bndy5 in [#52](https://github.com/cpp-linter/cpp-linter/pull/52)
- PR Review Suggestions by \@2bndy5 in [#51](https://github.com/cpp-linter/cpp-linter/pull/51)
- Support release drafter by \@shenxianpeng in [#54](https://github.com/cpp-linter/cpp-linter/pull/54)
- Change token to GITHUB_TOKEN for release drafter by \@shenxianpeng in [#62](https://github.com/cpp-linter/cpp-linter/pull/62)
- Allow PR review with no suggestions in diff by \@2bndy5 in [#68](https://github.com/cpp-linter/cpp-linter/pull/68)

### <!-- 4 --> 🐛 Bug fixes

- Thread-comments are not exclusive to github-actions bot by \@2bndy5 in [#53](https://github.com/cpp-linter/cpp-linter/pull/53)
- Remove duplicated file name in tidy comment by \@2bndy5 in [#64](https://github.com/cpp-linter/cpp-linter/pull/64)
- Resolves #65 by \@2bndy5 in [#66](https://github.com/cpp-linter/cpp-linter/pull/66)

### <!-- 6 --> 📦 Dependency updates

- Bump the major versions of some GH actions by \@2bndy5 in [#69](https://github.com/cpp-linter/cpp-linter/pull/69)
- Bump codecov-action to v4 by \@2bndy5 in [#71](https://github.com/cpp-linter/cpp-linter/pull/71)

### <!-- 9 --> 📝 Documentation

- Document PR review feature caveats by \@2bndy5 in [#70](https://github.com/cpp-linter/cpp-linter/pull/70)
- Auto update doc copyright year by \@2bndy5 in [#72](https://github.com/cpp-linter/cpp-linter/pull/72)

[1.7.0]: https://github.com/cpp-linter/cpp-linter/compare/v1.6.5...v1.7.0

Full commit diff: [`v1.6.5...v1.7.0`][1.7.0]

## [1.6.4] - 2023-12-19

### <!-- 4 --> 🐛 Bug fixes

- Use static method to parse diff without init-ing repo by \@2bndy5 in [#42](https://github.com/cpp-linter/cpp-linter/pull/42)

[1.6.4]: https://github.com/cpp-linter/cpp-linter/compare/v1.6.3...v1.6.4

Full commit diff: [`v1.6.3...v1.6.4`][1.6.4]

## [1.6.3] - 2023-12-14

### <!-- 4 --> 🐛 Bug fixes

- Fix annotations error counter by \@HerrCai0907 in [#41](https://github.com/cpp-linter/cpp-linter/pull/41)

[1.6.3]: https://github.com/cpp-linter/cpp-linter/compare/v1.6.2...v1.6.3

Full commit diff: [`v1.6.2...v1.6.3`][1.6.3]

## New Contributors

- @HerrCai0907 made their first contribution in [#41](https://github.com/cpp-linter/cpp-linter/pull/41)

## [1.6.2] - 2023-12-04

### <!-- 1 --> 🚀 New features and improvements

- Add more specific outputs by \@2bndy5 in [#37](https://github.com/cpp-linter/cpp-linter/pull/37)

[1.6.2]: https://github.com/cpp-linter/cpp-linter/compare/v1.6.1...v1.6.2

Full commit diff: [`v1.6.1...v1.6.2`][1.6.2]

## [1.6.1] - 2023-11-09

### <!-- 1 --> 🚀 New features and improvements

- Resolve #34 by \@2bndy5 in [#35](https://github.com/cpp-linter/cpp-linter/pull/35)

### <!-- 4 --> 🐛 Bug fixes

- Fix format comment by \@2bndy5 in [#36](https://github.com/cpp-linter/cpp-linter/pull/36)

[1.6.1]: https://github.com/cpp-linter/cpp-linter/compare/v1.6.0...v1.6.1

Full commit diff: [`v1.6.0...v1.6.1`][1.6.1]

## [1.6.0] - 2023-05-20

### <!-- 1 --> 🚀 New features and improvements

- Resolves #24 by \@2bndy5 in [#32](https://github.com/cpp-linter/cpp-linter/pull/32)

[1.6.0]: https://github.com/cpp-linter/cpp-linter/compare/v1.5.1...v1.6.0

Full commit diff: [`v1.5.1...v1.6.0`][1.6.0]

## [1.5.1] - 2022-12-13

### <!-- 1 --> 🚀 New features and improvements

- Keep all generated files in a cache folder by \@2bndy5 in [#29](https://github.com/cpp-linter/cpp-linter/pull/29)

[1.5.1]: https://github.com/cpp-linter/cpp-linter/compare/v1.5.0...v1.5.1

Full commit diff: [`v1.5.0...v1.5.1`][1.5.1]

## [1.5.0] - 2022-12-11

### <!-- 1 --> 🚀 New features and improvements

- Switch to diff format from REST API by \@2bndy5 in [#26](https://github.com/cpp-linter/cpp-linter/pull/26)

[1.5.0]: https://github.com/cpp-linter/cpp-linter/compare/v1.4.14...v1.5.0

Full commit diff: [`v1.4.14...v1.5.0`][1.5.0]

## [1.4.14] - 2022-11-17

### <!-- 4 --> 🐛 Bug fixes

- Resolve #22 by \@2bndy5 in [#23](https://github.com/cpp-linter/cpp-linter/pull/23)

[1.4.14]: https://github.com/cpp-linter/cpp-linter/compare/v1.4.13...v1.4.14

Full commit diff: [`v1.4.13...v1.4.14`][1.4.14]

## [1.4.13] - 2022-11-14

### <!-- 4 --> 🐛 Bug fixes

- Skip file when no new lines added and lines-changed-only is asserted by \@shenxianpeng in [#21](https://github.com/cpp-linter/cpp-linter/pull/21)

[1.4.13]: https://github.com/cpp-linter/cpp-linter/compare/v1.4.12...v1.4.13

Full commit diff: [`v1.4.12...v1.4.13`][1.4.13]

## [1.4.12] - 2022-11-08

### <!-- 1 --> 🚀 New features and improvements

- Adjust annotation display by \@shenxianpeng in [#20](https://github.com/cpp-linter/cpp-linter/pull/20)

[1.4.12]: https://github.com/cpp-linter/cpp-linter/compare/v1.4.11...v1.4.12

Full commit diff: [`v1.4.11...v1.4.12`][1.4.12]

## [1.4.11] - 2022-11-08

### <!-- 7 --> 🚦 Tests

- Codecov: Failed to properly upload by \@shenxianpeng in [#19](https://github.com/cpp-linter/cpp-linter/pull/19)

[1.4.11]: https://github.com/cpp-linter/cpp-linter/compare/v1.4.10...v1.4.11

Full commit diff: [`v1.4.10...v1.4.11`][1.4.11]

## [1.4.10] - 2022-11-05

### <!-- 1 --> 🚀 New features and improvements

- Add code style "chromium", "microsoft" to file annotation by \@shenxianpeng in [#15](https://github.com/cpp-linter/cpp-linter/pull/15)

[1.4.10]: https://github.com/cpp-linter/cpp-linter/compare/v1.4.9...v1.4.10

Full commit diff: [`v1.4.9...v1.4.10`][1.4.10]

## [1.4.9] - 2022-10-25

### <!-- 4 --> 🐛 Bug fixes

- Remove set-output instead of GITHUB_OUTPUT by \@shenxianpeng in [#13](https://github.com/cpp-linter/cpp-linter/pull/13)

[1.4.9]: https://github.com/cpp-linter/cpp-linter/compare/v1.4.8...v1.4.9

Full commit diff: [`v1.4.8...v1.4.9`][1.4.9]

## [1.4.8] - 2022-09-16

### <!-- 4 --> 🐛 Bug fixes

- Addresses #10 by \@2bndy5 in [#11](https://github.com/cpp-linter/cpp-linter/pull/11)

[1.4.8]: https://github.com/cpp-linter/cpp-linter/compare/v1.4.7...v1.4.8

Full commit diff: [`v1.4.7...v1.4.8`][1.4.8]

## [1.4.7] - 2022-09-08

### <!-- 9 --> 📝 Documentation

- Add cpp-linter download stats badge by \@shenxianpeng in [#6](https://github.com/cpp-linter/cpp-linter/pull/6)

[1.4.7]: https://github.com/cpp-linter/cpp-linter/compare/v1.4.6...v1.4.7

Full commit diff: [`v1.4.6...v1.4.7`][1.4.7]

## [1.4.6] - 2022-08-24

[1.4.6]: https://github.com/cpp-linter/cpp-linter/compare/255e740e0967c214af7b8382573476262b06921a...v1.4.6

Full commit diff: [`255e740...v1.4.6`][1.4.6]

## New Contributors

- @2bndy5 made their first contribution
- @shenxianpeng made their first contribution

<!-- generated by git-cliff -->
