Token Permissions
=================

.. _push events: https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#push
.. _pull_request events: https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#pull_request

This is an exhaustive list of required permissions organized by features.

File Changes
----------------------

When using :std:option:`--files-changed-only` or :std:option:`--lines-changed-only` to get the list
of file changes for a CI event, the following permissions are needed:

.. code-block:: yaml

    permissions:
      contents: read # (1)!

.. code-annotations::

    #. This permission is also needed to download files if the repository is not checked out before
       running cpp-linter (for both push and pull_request events).

Thread Comments
----------------------

The :std:option:`--thread-comments` feature requires the following permissions:

.. code-block:: yaml

    permissions:
      issues: write # (1)!
      pull_requests: write # (2)!

.. code-annotations::

    #. for `push events`_
    #. for `pull_request events`_

Pull Request Reviews
----------------------

The :std:option:`--tidy-review` and :std:option:`--format-review` features require the following permissions:


.. code-block:: yaml

    permissions:
      pull_requests: write
