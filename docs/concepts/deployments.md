---
description: Prefect deployments elevate flows, allowing flow runs to be scheduled and triggered via API. Learn how to easily manage your code and deployments.
tags:
    - orchestration
    - flow runs
    - deployments
    - schedules
    - triggers
    - infrastructure
    - storage
    - work pool
    - worker
search:
  boost: 2
---
# Deployments

Deployments are server-side representations of flows. 
They store the crucial metadata needed for remote orchestration including _when_, _where_, and _how_ a workflow should run.
Deployments elevate workflows from functions that you must call manually to API-managed entities that can be triggered remotely.

Here we will focus largely on the metadata that defines a deployment and how it is used. 
Different ways of creating a deployment populate these fields differently.

## Overview

Every Prefect deployment references one and only one "entrypoint" flow (though that flow may itself call any number of subflows). 
Different deployments may reference the same underlying flow, a useful pattern when developing or promoting workflow changes through staged environments.

The complete schema that defines a deployment is as follows:

```python
class Deployment:
    """
    Structure of the schema defining a deployment
    """

    # required defining data
    name: str 
    flow_id: UUID
    entrypoint: str
    path: str = None

    # workflow scheduling and parametrization
    parameters: dict = None
    parameter_openapi_schema: dict = None
    schedules: list[Schedule] = None
    paused: bool = False
    trigger: Trigger = None

    # metadata for bookkeeping
    version: str = None
    description: str = None
    tags: list = None

    # worker-specific fields
    work_pool_name: str = None
    work_queue_name: str = None
    infra_overrides: dict = None
    pull_steps: dict = None
```

All methods for creating Prefect deployments are interfaces for populating this schema. Let's look at each section in turn.

### Required data

Deployments universally require both a `name` and a reference to an underlying `Flow`.
In almost all instances of deployment creation, users do not need to concern themselves with the `flow_id` as most interfaces will only need the flow's name.
Note that the deployment name is not required to be unique across all deployments but is required to be unique for a given flow ID.
As a consequence, you will often see references to the deployment's unique identifying name `{FLOW_NAME}/{DEPLOYMENT_NAME}`.
For example, triggering a run of a deployment from the Prefect CLI can be done via:

<div class="terminal">
```bash
prefect deployment run my-first-flow/my-first-deployment
```
</div>

The other two fields are less obvious:

- **`path`**: the _path_ can generally be interpreted as the runtime working directory for the flow. 
For example, if a deployment references a workflow defined within a Docker image, the `path` will be the absolute path to the parent directory where that workflow will run anytime the deployment is triggered. 
This interpretation is more subtle in the case of flows defined in remote filesystems.
- **`entrypoint`**: the _entrypoint_ of a deployment is a relative reference to a function decorated as a flow that exists on some filesystem. 
It is always specified relative to the `path`. Entrypoints use Python's standard path-to-object syntax (e.g., `path/to/file.py:function_name` or simply `path:object`).

The entrypoint must reference the same flow as the flow ID.

Note that Prefect requires that deployments reference flows defined _within Python files_.
Flows defined within interactive REPLs or notebooks cannot currently be deployed as such. 
They are still valid flows that will be monitored by the API and observable in the UI whenever they are run, but Prefect cannot trigger them.

!!! info "Deployments do not contain code definitions"
    Deployment metadata references code that exists in potentially diverse locations within your environment.
    This separation of concerns means that your flow code stays within your storage and execution infrastructure and never lives on the Prefect server or database.

    This is the heart of the Prefect hybrid model: there's a boundary between your proprietary assets, such as your flow code, and the Prefect backend (including [Prefect Cloud](/cloud/)). 

### Scheduling and parametrization

One of the primary motivations for creating deployments of flows is to remotely _schedule_ and _trigger_ them.
Just as flows can be called as functions with different input values, so can deployments be triggered or scheduled with different values through the use of parameters.

The six fields here capture the necessary metadata to perform such actions:

- **`schedules`**: a list of [schedule objects](/concepts/schedules/).
Most of the convenient interfaces for creating deployments allow users to avoid creating this object themselves.
For example, when [updating a deployment schedule in the UI](/concepts/schedules/#creating-schedules-through-the-ui) basic information such as a cron string or interval is all that's required.
- **`trigger`** (Cloud-only): triggers allow you to define event-based rules for running a deployment.
For more information see [Automations](/concepts/automations/).
- **`parameter_openapi_schema`**: an [OpenAPI compatible schema](https://swagger.io/specification/) that defines the types and defaults for the flow's parameters.
This is used by both the UI and the backend to expose options for creating manual runs as well as type validation.
- **`parameters`**: default values of flow parameters that this deployment will pass on each run.
These can be overwritten through a trigger or when manually creating a custom run.
- **`enforce_parameter_schema`**: a boolean flag that determines whether the API should validate the parameters passed to a flow run against the schema defined by `parameter_openapi_schema`.

!!! tip "Scheduling is asynchronous and decoupled"
    Because deployments are nothing more than metadata, runs can be created at anytime.
    Note that pausing a schedule, updating your deployment, and other actions reset your auto-scheduled runs.

#### Running a deployed flow from within Python flow code

Prefect provides a [`run_deployment` function](/api-ref/prefect/deployments/deployments/#prefect.deployments.deployments.run_deployment) that can be used to schedule the run of an existing deployment when your Python code executes.

```python
from prefect.deployments import run_deployment

def main():
    run_deployment(name="my_flow_name/my_deployment_name")
```

!!! tip "Run a deployment without blocking"
    By default, `run_deployment` blocks until the scheduled flow run finishes
    executing. Pass `timeout=0` to return immediately and not block.
    
If you call `run_deployment` from within a flow or task, the scheduled flow
run will be linked to the calling flow run (or the calling task's flow run)
as a subflow run by default.

Subflow runs have different behavior than regular flow runs. For example, a 
subflow run can't be suspended independently of its parent flow. If you'd
rather not link the scheduled flow run to the calling flow or task run, you
can disable this behavior by passing `as_subflow=False`:

```python
from prefect import flow
from prefect.deployments import run_deployment


@flow
def my_flow():
    # The scheduled flow run will not be linked to this flow as a subflow.
    run_deployment(name="my_other_flow/my_deployment_name", as_subflow=False)
```

The return value of `run_deployment` is a [FlowRun](/api-ref/prefect/client/schemas/#prefect.client.schemas.objects.FlowRun) object containing metadata about the scheduled run. You
can use this object to retrieve information about the run after calling
`run_deployment`:

```python
from prefect import get_client
from prefect.deployments import run_deployment

def main():
    flow_run = run_deployment(name="my_flow_name/my_deployment_name")
    flow_run_id = flow_run.id

    # If you save the flow run's ID, you can use it later to retrieve
    # flow run metadata again, e.g. to check if it's completed.
    async with get_client() as client:
        flow_run = client.read_flow_run(flow_run_id)
        print(f"Current state of the flow run: {flow_run.state}")
```

!!! tip "Using the Prefect client"
    For more information on using the Prefect client to interact with Prefect's
    REST API, see [our guide](/guides/using-the-client/).

## Versioning and bookkeeping

Versions, descriptions and tags are omnipresent fields throughout Prefect that can be easy to overlook. However, putting some extra thought into how you use these fields can pay dividends down the road.

- **`version`**: versions are always set by the client and can be any arbitrary string. 
We recommend tightly coupling this field on your deployments to your software development lifecycle. 
For example if you leverage `git` to manage code changes, use either a tag or commit hash in this field. If you don't set a value for the version, Prefect will compute a hash
- **`description`**: the description field of a deployment is a place to provide rich reference material for downstream stakeholders such as intended use and parameter documentation. Markdown formatting will be rendered in the Prefect UI, allowing for section headers, links, tables, and other formatting. If not provided explicitly, Prefect will use the docstring of your flow function as a default value.
- **`tags`**: tags are a mechanism for grouping related work together across a diverse set of objects. Tags set on a deployment will be inherited by that deployment's flow runs. These tags can then be used to filter what runs are displayed on the primary UI dashboard, allowing you to customize different views into your work. In addition, in Prefect Cloud you can easily find objects through searching by tag.

All of these bits of metadata can be leveraged to great effect by injecting them into the processes that Prefect is orchestrating. For example you can use both run ID and versions to organize files that you produce from your workflows, or by associating your flow run's tags with the metadata of a job it orchestrates.
This metadata is available during execution through [Prefect runtime](/guides/runtime-context/).

!!! tip "Everything has a version"
    Deployments aren't the only entity in Prefect with a version attached; both flows and tasks also have versions that can be set through their respective decorators. These versions will be sent to the API anytime the flow or task is run and thereby allow you to audit your changes across all levels.

### Workers and Work Pools

[Workers and work pools](/concepts/work-pools/) are an advanced deployment pattern that allow you to dynamically provision infrastructure for each flow run.
In addition, the work pool job template interface allows users to create and govern opinionated interfaces to their workflow infrastructure.
To do this, a deployment using workers needs to evaluate the following fields:

- **`work_pool_name`**: the name of the work pool this deployment will be associated with.
Work pool types mirror infrastructure types and therefore the decision here affects the options available for the other fields.
- **`work_queue_name`**: if you are using work queues to either manage priority or concurrency, you can associate a deployment with a specific queue within a work pool using this field.
- **`infra_overrides`**: often called `job_variables` within various interfaces, this field allows deployment authors to customize whatever infrastructure options have been exposed on this work pool.
This field is often used for things such as Docker image names, Kubernetes annotations and limits, and environment variables.
- **`pull_steps`**: a JSON description of steps that should be performed to retrieve flow code or configuration and prepare the runtime environment for workflow execution.

Pull steps allow users to highly decouple their workflow architecture.
For example, a common use of pull steps is to dynamically pull code from remote filesystems such as GitHub with each run of their deployment.

For more information see [the guide to deploying with a worker](/guides/prefect-deploy/).

## Two approaches to deployments

There are two primary ways to deploy flows with Prefect, differentiated by how much control Prefect has over the infrastructure in which the flows run.

In one setup, deploying Prefect flows is analogous to deploying a webserver - users author their workflows and then start a long-running process (often within a Docker container) that is responsible for managing all of the runs for the associated deployment(s).

In the other setup, you do a little extra up-front work to set up a [work pool and a base job template that defines how individual flow runs will be submitted to infrastructure](/guides/prefect-deploy).

Prefect provides several [types of work pools](/concepts/work-pools/#work-pool-types) corresponding to different types of infrastructure.
Prefect Cloud provides a [Prefect Managed work pool](/guides/managed-execution/) option that is the simplest way to run workflows remotely.
A cloud-provider account, such as AWS, is not required with a Prefect Managed work pool.

Some work pool types require a client-side worker to submit job definitions to the appropriate infrastructure with each run.

Each of these setups can support production workloads. 
The choice ultimately boils down to your use case and preferences. 
Read further to decide which setup is best for your situation.

### Serving flows on long-lived infrastructure

When you have several flows running regularly, [the `serve` method](/concepts/flows/#serving-a-flow) of the `Flow` object or [the `serve` utility](/concepts/flows/#serving-multiple-flows-at-once) is a great option for managing multiple flows simultaneously.

Once you have authored your flow and decided on its deployment settings as described above, all that's left is to run this long-running process in a location of your choosing.
The process will stay in communication with the Prefect API, monitoring for work and submitting each run within an individual subprocess.
Note that because runs are submitted to subprocesses, any external infrastructure configuration will need to be setup beforehand and kept associated with this process.

This approach has many benefits:

- Users are in complete control of their infrastructure, and anywhere the "serve" Python process can run is a suitable deployment environment.
- It is simple to reason about.
- Creating deployments requires a minimal set of decisions.
- Iteration speed is fast.

However, there are a few reasons you might consider running flows on dynamically provisioned infrastructure with work pools instead:

- Flows that have expensive infrastructure needs may be more costly in this setup due to the long-running process.
- Flows with heterogeneous infrastructure needs across runs will be more difficult to configure and schedule.
- Large volumes of deployments can be harder to track.
- If your internal team structure requires that deployment authors be members of a different team than the team managing infrastructure, the work pool interface may be preferred.

### Dynamically provisioning infrastructure with work pools

[Work pools](/concepts/work-pools/) allow Prefect to exercise greater control of the infrastructure on which flows run.
Options for [serverless work pools](/guides/deployment/serverless-workers/) allow you to scale to zero when workflows aren't running.
Prefect even provides you with the ability to [provision cloud infrastructure via a single CLI command](/guides/deployment/push-work-pools/#automatically-creating-a-new-push-work-pool-and-provisioning-infrastructure), if you use a Prefect Cloud push work pool option.

With work pools:

- You can configure and monitor infrastructure configuration within the Prefect UI.
- Infrastructure is ephemeral and dynamically provisioned.
- Prefect is more infrastructure-aware and therefore collects more event data from your infrastructure by default.
- Highly decoupled setups are possible.

!!! note "You don't have to commit to one approach"
    You are not required to use only one of these approaches for your deployments. You can mix and match approaches based on the needs of each flow. Further, you can change the deployment approach for a particular flow as its needs evolve.
    For example, you might use workers for your expensive machine learning pipelines, but use the serve mechanics for smaller, more frequent file-processing pipelines.
