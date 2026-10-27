.. _labgrid-client:

labgrid-client CLI
==================

Labgrid is a scalable infrastructure and test architecture for embedded (linux) systems.

This is the client to control a boards status and interface with it on remote machines.

.. currentmodule:: labgrid.remote.client


.. autoprogram:: labgrid.remote.client:get_parser(auto_doc_mode=True)
   :prog: labgrid-client

Isolated command sessions (JappyJan fork)
----------------------------------------

Use a single session for a complete hardware operation. Build before reserving::

   labgrid-client -x lab-host:20408 session --filter board=reader \
       --purpose 'ATT-1154: firmware validation' --wait-timeout 300 \
       -- sh -c 'labgrid-client show; python validate.py'

Use ``-p reader-1`` before ``session`` to reserve one specific place, or repeated
``--filter KEY=VALUE`` arguments to select any compatible place. Reservations
use the coordinator's existing priority/age scheduler. The allocation wait is
bounded; the child command's duration is not limited.

Each invocation has a unique native client identity, including when clients
share a host, login and SSH credentials. The child inherits that identity and
``LG_PLACE``, ``LG_TOKEN``, ``LG_COORDINATOR``, ``LG_SESSION_ID``,
``LG_SESSION_PURPOSE`` and ``LG_ARTIFACTS``. ``-c ENV.yaml`` supplies ``LG_ENV``.
The artifact directory is a unique subdirectory of ``--artifacts`` (default
``lab-artifacts``) and contains lifecycle metadata in ``session.json``.
Child output remains attached to the caller; save evidence in ``LG_ARTIFACTS``.
The client's Python environment is prepended to the child's ``PATH`` so Python
scripts and native commands use the same installed dependencies.

Use native commands inside the child without independently acquiring or
releasing the place. Nested sessions are rejected. The child and descendants
are stopped before the reservation and claim are released, including on
failure, SIGINT or SIGTERM. The command's exit status is preserved.
A lost claim or failed reservation keepalive stops the child.

SIGKILL of the parent and host failure can leave a claim and child processes
behind. Inspect ``who``, metadata and process state, stop the abandoned hardware
operation, then deliberately recover with ``release --kick`` and
``cancel-reservation TOKEN``. There is no automatic takeover or claim expiry.
This coordinates trusted clients; identity variables are not authentication.

Install the optional agent skill by linking ``contrib/skills/labgrid`` into
your agent's global skills directory. No MCP server is required. This client
extension is based on labgrid 26.0.1 and requires no coordinator/exporter
changes when connecting to a labgrid 26.x deployment.

Configuration File
------------------
The configuration file follows the description in ``labgrid-device-config``\(5).

Environment Variables
---------------------
Various labgrid-client commands use the following environment variable:

LG_PLACE
~~~~~~~~
This variable can be used to specify a place without using the ``-p`` option, the ``-p`` option overrides it.

LG_TOKEN
~~~~~~~~
This variable can be used to specify a reservation for the ``wait`` command and
for the ``+`` place expansion.

LG_STATE
~~~~~~~~
This variable can be used to specify a state which the device transitions into
before executing a command. Requires a configuration file and a Strategy
specified for the device.

LG_INITIAL_STATE
~~~~~~~~~~~~~~~~
This variable can be used to specify an initial state the device is known to
be in.
This is useful during development. The Strategy used must implement the
``force()`` method.
A desired state must be set using ``LG_STATE`` or ``-s``/``--state``.

LG_ENV
~~~~~~
This variable can be used to specify the configuration file to use without
using the ``--config`` option, the ``--config`` option overrides it.

LG_COORDINATOR
~~~~~~~~~~~~~~
This variable can be used to set the default coordinator in the format
``HOST[:PORT]`` (instead of using the ``-x`` option).

LG_PROXY
~~~~~~~~
This variable can be used to specify a SSH proxy hostname which should be used
to connect to the coordinator and any resources which are normally accessed
directly.

LG_HOSTNAME
~~~~~~~~~~~
Override the hostname used when accessing a resource. Typically only useful for
CI pipelines where the hostname may not be consistent between pipeline stages.

LG_USERNAME
~~~~~~~~~~~
Override the username used when accessing a resource. Typically only useful for
CI pipelines where the username may not be consistent between pipeline stages.

LG_SSH_CONNECT_TIMEOUT
~~~~~~~~~~~~~~~~~~~~~~
Set the connection timeout when using SSH (The ``ConnectTimeout`` option). If
unspecified, defaults to 30 seconds.

LG_AGENT_PREFIX
~~~~~~~~~~~~~~~~~~~~~~
Add a prefix to ``.labgrid_agent_{agent_hash}.py`` allowing specification for
where on the exporter it should be uploaded to. 

Matches
-------
Match patterns are used to assign a resource to a specific place. The format is:
exporter/group/cls/name, exporter is the name of the exporting machine, group is
a name defined within the exporter, cls is the class of the exported resource
and name is its name. Wild cards in match patterns are explicitly allowed, *
matches anything.

Adding Named Resources
----------------------
If a target contains multiple Resources of the same type, named matches need to
be used to address the individual resources. In addition to the *match* taken by
``add-match``, ``add-named-match`` also takes a name for the resource. The other
client commands support the name as an optional parameter and will inform the
user that a name is required if multiple resources are found, but no name is
given.

If one of the resources should be used by default when no resource name is
explicitly specified, it can be named ``default``.

Examples
--------

To retrieve a list of places run:

.. code-block:: bash

   $ labgrid-client places

To access a place, it needs to be acquired first, this can be done by running
the ``acquire command`` and passing the placename as a -p parameter:

.. code-block:: bash

   $ labgrid-client -p <placename> acquire

Open a console to the acquired place:

.. code-block:: bash

   $ labgrid-client -p <placename> console

Add all resources with the group "example-group" to the place example-place:

.. code-block:: bash

   $ labgrid-client -p example-place add-match */example-group/*/*

See Also
--------

``labgrid-exporter``\(1)
