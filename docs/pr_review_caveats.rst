Pull Request Review Caveats
===========================

.. _repository settings: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository#preventing-github-actions-from-creating-or-approving-pull-requests
.. _organization settings: https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository#preventing-github-actions-from-creating-or-approving-pull-requests

.. hint::

    This information is specific to GitHub Pull Requests (often abbreviated as "PR").

While the Pull Request review feature has been diligently tested, there are still some caveats to
beware of when using Pull Request reviews.

Bot Permissions required
------------------------

The "GitHub Actions" bot may need to be allowed to approve Pull Requests.
By default, the bot cannot approve Pull Request changes, only request more changes.
This will show as a warning in the workflow logs if the given token (set to the
environment variable ``GITHUB_TOKEN``) isn't configured with the proper permissions.

.. seealso::

    Refer to the GitHub documentation for `repository settings`_ or `organization settings`_
    about adjusting the required permissions for GitHub Actions's ``secrets.GITHUB_TOKEN``.

    See also our :std:doc:`required token permissions <permissions>`.

Auto-disabled for certain event types
-------------------------------------

The feature is auto-disabled for

- closed Pull Requests
- locked Pull Requests
- Pull Requests marked as "draft"
- push events

Previous reviews are reused or cleaned up
-----------------------------------------

Clang-tidy and clang-format suggestions are shown in 1 Pull Request review.

- Users are encouraged to choose either :std:option:`--tidy-review` or :std:option:`--format-review`.
  Enabling both will likely show duplicate or similar suggestions.
  Remember, clang-tidy can be configured to use the same ``style`` that clang-format accepts.
  There is no current implementation to combine suggestions from both tools (clang-tidy kind of
  does that anyway).

Before posting a new review, cpp-linter checks the reviews it posted in previous runs on the same
Pull Request:

- A suggestion that was already posted is reused instead of being posted again.
  The new review's summary comment says how many suggestions were reused.
  If every suggestion was already posted, then no new review is posted at all.
- A previous suggestion that no longer applies is marked as resolved.
  Its conversation is not deleted, so any replies from other users are preserved.
- A previous review that has no reused suggestions is dismissed, and its summary comment is
  hidden (as "outdated").

A suggestion is only reused if it is identical to a previous one: same file, same lines, and same
text. So, a suggestion may be posted again if the lines it targets have moved
(for example, because lines were added above it).
Suggestions in a conversation that was already resolved (or hidden) are never reused.
This means that if a user manually resolves a suggestion without addressing it, then the
suggestion will be posted again in the next review.

.. note::

    Reviews are only reused or cleaned up if they were posted by cpp-linter.
    Reviews from other users or bots are left as is.

.. tip::

    We do support an environment variable named ``CPP_LINTER_PR_REVIEW_SUMMARY_ONLY``.
    If the variable is set either ``true``, ``on``, or ``1``, then the review only
    contains a summary comment with no suggestions posted in the diff.

Probable non-exhaustive reviews
-------------------------------

If any suggestions did not fit within the Pull Request diff, then the review's summary comment will
indicate how many suggestions were left out.
The full patch of suggestions is always included as a collapsed code block in the review summary
comment. This isn't a problem we can fix.
GitHub won't allow review comments/suggestions to target lines that are not shown in the Pull
Request diff (the summation of file differences in a Pull Request).

- Users are encouraged to set :std:option:`--lines-changed-only` to ``true``.
  This will *help* us keep the suggestions limited to lines that are shown within the Pull
  Request diff.
  However, there are still some cases where clang-format or clang-tidy will apply fixes to lines
  that are not within the diff.
  This can't be avoided because the ``--line-filter`` passed to the clang-tidy (and ``--lines``
  passed to clang-format) only applies to analysis, not fixes.
- Not every diagnostic from clang-tidy can be automatically fixed.
  Some diagnostics require user interaction/decision to properly address.
- Some fixes provided might depend on what compiler is used.
  We have made it so clang-tidy takes advantage of any fixes provided by the compiler.
  Compilation errors may still prevent clang-tidy from reporting all concerns.
