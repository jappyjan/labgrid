"""A native reservation and claim scoped to one foreground command."""

import asyncio
import contextlib
import json
import os
from pathlib import Path
import signal
import sys
import time

from .common import Reservation, ReservationState, TAG_KEY, TAG_VAL
from .generated import labgrid_coordinator_pb2 as messages


async def run_session(session, *, user_error, command_error):

    args = session.args
    filters = {}
    for pair in args.filter:
        key, separator, value = pair.partition("=")
        if not separator or not TAG_KEY.match(key) or not TAG_VAL.match(value):
            raise user_error(f"invalid reservation filter: {pair!r}")
        filters[key] = value
    if args.place:
        filters["name"] = session.get_place(args.place).name

    artifacts = Path(args.artifacts).resolve() / args.session_id
    artifacts.mkdir(parents=True, mode=0o700)
    owner = f"{session.gethostname()}/{session.getuser()}"
    metadata = {"id": args.session_id, "owner": owner, "purpose": args.purpose,
                "coordinator": session.address, "state": "waiting", "started": time.time()}

    def record():
        temporary = artifacts / "session.json.tmp"
        temporary.write_text(json.dumps(metadata, indent=2) + "\n")
        temporary.replace(artifacts / "session.json")

    record()
    print(f"Session {args.session_id}: {args.purpose}\nArtifacts: {artifacts}", file=sys.stderr, flush=True)
    token = place = process = None
    tasks = []
    attempted = False
    try:
        # Shield creation so cancellation cannot lose the token before cleanup.
        creation = asyncio.ensure_future(session.stub.CreateReservation(
            messages.CreateReservationRequest(filters={
                "main": messages.Reservation.Filter(filter=filters)
            }), timeout=10))
        try:
            response = await asyncio.shield(creation)
        finally:
            response = await creation
            token = response.reservation.token
            metadata["reservation"] = token
            record()

        deadline = time.monotonic() + args.wait_timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise user_error("timed out waiting for a matching place")
            response = await session.stub.PollReservation(
                messages.PollReservationRequest(token=token), timeout=min(10, remaining))
            reservation = Reservation.from_pb2(response.reservation)
            if reservation.state is ReservationState.allocated:
                place, = reservation.allocations["main"]
                break
            if reservation.state is not ReservationState.waiting:
                raise user_error(f"reservation entered state {reservation.state.name}")
            await asyncio.sleep(min(1, remaining))

        if not await asyncio.wait_for(session.sync_with_coordinator(), timeout=10):
            raise user_error("coordinator stream disconnected before acquisition")
        metadata["place"] = place
        record()
        attempted = True
        await asyncio.wait_for(session._acquire_place(place), timeout=max(.001, deadline - time.monotonic()))
        metadata.update(place=place, state="running")
        record()
        child_env = os.environ.copy()
        child_env.update(LG_SESSION_ID=args.session_id, LG_SESSION_PURPOSE=args.purpose,
                         LG_PLACE=place, LG_TOKEN=token, LG_COORDINATOR=session.address,
                         LG_ARTIFACTS=str(artifacts))
        if args.config:
            child_env["LG_ENV"] = str(Path(args.config).resolve())
        spawning = asyncio.create_task(asyncio.create_subprocess_exec(
            *args.child, env=child_env, start_new_session=True))
        try:
            process = await asyncio.shield(spawning)
        finally:
            # A signal during spawn must not lose a running child's process group.
            process = await spawning

        async def keepalive():
            while True:
                await asyncio.sleep(1)
                await session.stub.PollReservation(messages.PollReservationRequest(token=token), timeout=10)
                if not await asyncio.wait_for(session.sync_with_coordinator(), timeout=10):
                    raise user_error("coordinator stream disconnected; stopping child command")
                if session.get_place(place).acquired != owner:
                    raise user_error("session lost its claim; stopping child command")

        tasks = [asyncio.create_task(process.wait()), asyncio.create_task(keepalive())]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        metadata["exit_code"] = process.returncode
        if process.returncode:
            code = process.returncode if process.returncode > 0 else 128 - process.returncode
            raise command_error("session command failed", code)
    finally:
        async def cleanup():
            # Stop descendants before releasing hardware, including background children.
            if process is not None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                # Drop the reservation while still holding the claim. Releasing last
                # lets the native scheduler immediately allocate the next waiter.
                if token:
                    await session.stub.CancelReservation(messages.CancelReservationRequest(token=token), timeout=10)
            finally:
                if attempted:
                    await session.stub.ReleasePlace(
                        messages.ReleasePlaceRequest(placename=place, fromuser=owner), timeout=10)

        cleaning = asyncio.create_task(cleanup())
        try:
            try:
                await asyncio.shield(cleaning)
            finally:
                # Also finish cleanup if the first signal arrives during cleanup.
                await cleaning
        except BaseException:
            if cleaning.done() and not cleaning.cancelled() and cleaning.exception() is None:
                metadata.update(state="finished", finished=time.time())
            else:
                metadata.update(state="recovery-required", finished=time.time())
            record()
            raise
        else:
            metadata.update(state="finished", finished=time.time())
            record()
