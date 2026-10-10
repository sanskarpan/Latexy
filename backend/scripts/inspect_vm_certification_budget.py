"""Read-only metadata for this exact temporary certification app name."""

import asyncio
import json

from modal.client import _Client
from modal_proto import api_pb2


async def main():
    client = await _Client.from_env()
    apps = await client.stub.AppList(api_pb2.AppListRequest())
    records = []
    for app in apps.apps:
        if app.name != "latexy-engine-vm-certification-20261007" and app.description != "latexy-engine-vm-certification-20261007":
            continue
        response = await client.stub.SandboxList(api_pb2.SandboxListRequest(app_id=app.app_id, include_finished=True))
        for sandbox in response.sandboxes:
            task = sandbox.task_info
            records.append({"seconds_upper": max(0, task.finished_at - sandbox.created_at) if task.finished_at else None,
                            "finished": bool(task.finished_at)})
    known = bool(records) and all(row["seconds_upper"] is not None for row in records)
    seconds = sum(row["seconds_upper"] for row in records) if known else None
    print(json.dumps({"records": records, "known": known, "total_seconds_upper": seconds,
                      "compute_usd_upper": seconds * (2 * 0.00003942 + 2 * 0.00000667) if known else None}))


if __name__ == "__main__":
    asyncio.run(main())
