"""
Routes for interacting with task run objects.
"""

import datetime
from typing import List
from uuid import UUID

import pendulum
from prefect._vendor.fastapi import (
    Body,
    Depends,
    HTTPException,
    Path,
    Response,
    WebSocket,
    status,
)

import prefect.server.api.dependencies as dependencies
import prefect.server.models as models
import prefect.server.schemas as schemas
from prefect.logging import get_logger
from prefect.server.api.run_history import run_history
from prefect.server.database.dependencies import provide_database_interface
from prefect.server.database.interface import PrefectDBInterface
from prefect.server.orchestration import dependencies as orchestration_dependencies
from prefect.server.orchestration.policies import BaseOrchestrationPolicy
from prefect.server.schemas.responses import OrchestrationResult
from prefect.server.task_queue import MultiQueue, TaskQueue
from prefect.server.utilities import subscriptions
from prefect.server.utilities.schemas import DateTimeTZ
from prefect.server.utilities.server import PrefectRouter

logger = get_logger("server.api")


router = PrefectRouter(prefix="/task_runs", tags=["Task Runs"])


@router.post("/")
async def create_task_run(
    task_run: schemas.actions.TaskRunCreate,
    response: Response,
    db: PrefectDBInterface = Depends(provide_database_interface),
    orchestration_parameters: dict = Depends(
        orchestration_dependencies.provide_task_orchestration_parameters
    ),
) -> schemas.core.TaskRun:
    """
    Create a task run. If a task run with the same flow_run_id,
    task_key, and dynamic_key already exists, the existing task
    run will be returned.

    If no state is provided, the task run will be created in a PENDING state.
    """
    # hydrate the input model into a full task run / state model
    task_run = schemas.core.TaskRun(**task_run.dict())

    if not task_run.state:
        task_run.state = schemas.states.Pending()

    now = pendulum.now("UTC")

    async with db.session_context(begin_transaction=True) as session:
        model = await models.task_runs.create_task_run(
            session=session,
            task_run=task_run,
            orchestration_parameters=orchestration_parameters,
        )

    if model.created >= now:
        response.status_code = status.HTTP_201_CREATED

    new_task_run: schemas.core.TaskRun = schemas.core.TaskRun.from_orm(model)

    return new_task_run


@router.patch("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_task_run(
    task_run: schemas.actions.TaskRunUpdate,
    task_run_id: UUID = Path(..., description="The task run id", alias="id"),
    db: PrefectDBInterface = Depends(provide_database_interface),
):
    """
    Updates a task run.
    """
    async with db.session_context(begin_transaction=True) as session:
        result = await models.task_runs.update_task_run(
            session=session, task_run=task_run, task_run_id=task_run_id
        )
    if not result:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task run not found")


@router.post("/count")
async def count_task_runs(
    db: PrefectDBInterface = Depends(provide_database_interface),
    flows: schemas.filters.FlowFilter = None,
    flow_runs: schemas.filters.FlowRunFilter = None,
    task_runs: schemas.filters.TaskRunFilter = None,
    deployments: schemas.filters.DeploymentFilter = None,
) -> int:
    """
    Count task runs.
    """
    async with db.session_context() as session:
        return await models.task_runs.count_task_runs(
            session=session,
            flow_filter=flows,
            flow_run_filter=flow_runs,
            task_run_filter=task_runs,
            deployment_filter=deployments,
        )


@router.post("/history")
async def task_run_history(
    history_start: DateTimeTZ = Body(..., description="The history's start time."),
    history_end: DateTimeTZ = Body(..., description="The history's end time."),
    history_interval: datetime.timedelta = Body(
        ...,
        description=(
            "The size of each history interval, in seconds. Must be at least 1 second."
        ),
        alias="history_interval_seconds",
    ),
    flows: schemas.filters.FlowFilter = None,
    flow_runs: schemas.filters.FlowRunFilter = None,
    task_runs: schemas.filters.TaskRunFilter = None,
    deployments: schemas.filters.DeploymentFilter = None,
    db: PrefectDBInterface = Depends(provide_database_interface),
) -> List[schemas.responses.HistoryResponse]:
    """
    Query for task run history data across a given range and interval.
    """
    if history_interval < datetime.timedelta(seconds=1):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="History interval must not be less than 1 second.",
        )

    async with db.session_context() as session:
        return await run_history(
            session=session,
            run_type="task_run",
            history_start=history_start,
            history_end=history_end,
            history_interval=history_interval,
            flows=flows,
            flow_runs=flow_runs,
            task_runs=task_runs,
            deployments=deployments,
        )


@router.get("/{id}")
async def read_task_run(
    task_run_id: UUID = Path(..., description="The task run id", alias="id"),
    db: PrefectDBInterface = Depends(provide_database_interface),
) -> schemas.core.TaskRun:
    """
    Get a task run by id.
    """
    async with db.session_context() as session:
        task_run = await models.task_runs.read_task_run(
            session=session, task_run_id=task_run_id
        )
    if not task_run:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task_run


@router.post("/filter")
async def read_task_runs(
    sort: schemas.sorting.TaskRunSort = Body(schemas.sorting.TaskRunSort.ID_DESC),
    limit: int = dependencies.LimitBody(),
    offset: int = Body(0, ge=0),
    flows: schemas.filters.FlowFilter = None,
    flow_runs: schemas.filters.FlowRunFilter = None,
    task_runs: schemas.filters.TaskRunFilter = None,
    deployments: schemas.filters.DeploymentFilter = None,
    db: PrefectDBInterface = Depends(provide_database_interface),
) -> List[schemas.core.TaskRun]:
    """
    Query for task runs.
    """
    async with db.session_context() as session:
        return await models.task_runs.read_task_runs(
            session=session,
            flow_filter=flows,
            flow_run_filter=flow_runs,
            task_run_filter=task_runs,
            deployment_filter=deployments,
            offset=offset,
            limit=limit,
            sort=sort,
        )


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_run(
    task_run_id: UUID = Path(..., description="The task run id", alias="id"),
    db: PrefectDBInterface = Depends(provide_database_interface),
):
    """
    Delete a task run by id.
    """
    async with db.session_context(begin_transaction=True) as session:
        result = await models.task_runs.delete_task_run(
            session=session, task_run_id=task_run_id
        )
    if not result:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Task not found")


@router.post("/{id}/set_state")
async def set_task_run_state(
    task_run_id: UUID = Path(..., description="The task run id", alias="id"),
    state: schemas.actions.StateCreate = Body(..., description="The intended state."),
    force: bool = Body(
        False,
        description=(
            "If false, orchestration rules will be applied that may alter or prevent"
            " the state transition. If True, orchestration rules are not applied."
        ),
    ),
    db: PrefectDBInterface = Depends(provide_database_interface),
    response: Response = None,
    task_policy: BaseOrchestrationPolicy = Depends(
        orchestration_dependencies.provide_task_policy
    ),
    orchestration_parameters: dict = Depends(
        orchestration_dependencies.provide_task_orchestration_parameters
    ),
) -> OrchestrationResult:
    """Set a task run state, invoking any orchestration rules."""

    now = pendulum.now("UTC")

    # create the state
    async with db.session_context(
        begin_transaction=True, with_for_update=True
    ) as session:
        orchestration_result = await models.task_runs.set_task_run_state(
            session=session,
            task_run_id=task_run_id,
            state=schemas.states.State.parse_obj(
                state
            ),  # convert to a full State object
            force=force,
            task_policy=task_policy,
            orchestration_parameters=orchestration_parameters,
        )

    # set the 201 if a new state was created
    if orchestration_result.state and orchestration_result.state.timestamp >= now:
        response.status_code = status.HTTP_201_CREATED
    else:
        response.status_code = status.HTTP_200_OK

    return orchestration_result


@router.websocket("/subscriptions/scheduled")
async def scheduled_task_subscription(websocket: WebSocket):
    websocket = await subscriptions.accept_prefect_socket(websocket)
    if not websocket:
        return

    try:
        subscription = await websocket.receive_json()
        task_keys = subscription.get("keys", [])
        if not task_keys:
            return await websocket.close()
    except subscriptions.NORMAL_DISCONNECT_EXCEPTIONS:
        return await websocket.close()

    subscribed_queue = MultiQueue(task_keys)

    while True:
        task_run = await subscribed_queue.get()

        try:
            await websocket.send_json(task_run.dict(json_compatible=True))

            acknowledgement = await websocket.receive_json()
            if acknowledgement.get("type") != "ack":
                return await websocket.close()

        except subscriptions.NORMAL_DISCONNECT_EXCEPTIONS:
            # If sending fails or pong fails, put the task back into the retry queue
            await TaskQueue.for_key(task_run.task_key).retry(task_run)
            return
