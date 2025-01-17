Reference
=========

Usage
-----

.. code::

    e4s-cl [ OPTIONS ] OBJECT { COMMAND }

    OBJECT := { init | launch | profile }

Options
--------

-V, --version		print the version information of **e4s-cl** and exit
-v, --verbose		print debugging information during execution
-d, --dry-run		do nothing; print what would have been done instead

Description
-------------

This top level command is the entry-point to the application. Options given here will influence all modes of operation, but the command by itself does not amount to any operation.

.. admonition:: Implicit sub-command

    When **e4s-cl** is called without a proper sub-command (:code:`init`, :code:`launch` or :code:`profile`), the program will implicitly use the :code:`launch` sub-command. This requires a complete profile to be selected as no launch arguments can be passed.

Sub-Commands Description
---------------------------

.. toctree::
   :maxdepth: 1

   init
   launch
   profiles/index.rst


