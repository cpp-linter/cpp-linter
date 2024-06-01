Token Permissions
=================

.. _push events: https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#push
.. _pull_request events: https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#pull_request

.. role:: yaml(code)
  :language: yaml
  :class: highlight

This is an exhaustive list of required permissions organized by features.

File Changes
----------------------

When using :std:option:`--files-changed-only` or :std:option:`--lines-changed-only` to get the list
of file changes for a CI event, the following permissions are needed:

.. md-tab-set::

  .. md-tab-item:: :yaml:`on: push`

      For `push events`_

      .. code-block:: yaml

          permissions:
            contents: read # (1)!

      .. code-annotations::

          #. This permission is also needed to download files if the repository is not checked out before
             running cpp-linter.

  .. md-tab-item:: :yaml:`on: pull_request`

      For `pull_request events`_

      .. code-block:: yaml

          permissions:
            contents: read # (1)!
            pull-requests: read # (2)!

      .. code-annotations::

          #. This permission is also needed to download files if the repository is not checked out before
             running cpp-linter.
          #. Specifying :yaml:`write` is also sufficient as that is required for

             * posting `thread comments`_ on pull requests
             * posting `pull request reviews`_

.. _thread comments:

Thread Comments
----------------------

The :std:option:`--thread-comments` feature requires the following permissions:

.. md-tab-set::

  .. md-tab-item:: :yaml:`on: push`

      For `push events`_

      .. code-block:: yaml

          permissions:
            metadata: read # (1)!
            contents: write # (2)!

      .. code-annotations::

          #. needed to fetch existing comments
          #. needed to post or update a commit comment. This also allows us to
             delete an outdated comment if needed.

  .. md-tab-item:: :yaml:`on: pull_request`

      For `pull_request events`_

      .. code-block:: yaml

          permissions:
            pull-requests: write

.. _pull request reviews:

Pull Request Reviews
----------------------

The :std:option:`--tidy-review`, :std:option:`--format-review`, and :std:option:`--passive-reviews`
features require the following permissions:

.. code-block:: yaml

    permissions:
      pull-requests: write
