"""Cost control, the floor under `make destroy` (Cloud Run functions, Python 3.12).

  budget_guard  fires on every budget notification. At the last alert level it DISABLES the deployer service
                account: nothing can be applied until the author re-enables it by hand. Disabled, not deleted.
  reaper        runs daily. It deletes BigQuery datasets labelled project=steward whose expires-at has passed.
                Datasets only (that is where data and cost live); everything else is removed by destroy.yml.

The decisions are in logic.py. This file only calls Google.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import functions_framework
from logic import decode_budget_message, expired, spend_reached


@functions_framework.cloud_event
def budget_guard(cloud_event) -> None:
    message = decode_budget_message(cloud_event.data)
    stop_at = float(os.environ["GUARD_STOP_AT"])
    print(f"budget notification: {message.get('budgetDisplayName')} cost {message.get('costAmount')} stop at {stop_at}")
    if not spend_reached(message, stop_at):
        return
    from googleapiclient import discovery

    iam = discovery.build("iam", "v1", cache_discovery=False)
    name = f"projects/{os.environ['PROJECT_ID']}/serviceAccounts/{os.environ['DEPLOYER_EMAIL']}"
    iam.projects().serviceAccounts().disable(name=name, body={}).execute()
    print(f"DISABLED {os.environ['DEPLOYER_EMAIL']}: spend reached {stop_at}")


@functions_framework.http
def reaper(request):
    from google.cloud import bigquery

    today = datetime.now(UTC).date()
    client = bigquery.Client(project=os.environ["PROJECT_ID"])
    deleted = []
    for item in client.list_datasets(filter="labels.project:steward"):
        dataset = client.get_dataset(item.reference)
        if expired(dataset.labels, today):
            client.delete_dataset(dataset, delete_contents=True, not_found_ok=True)
            deleted.append(dataset.dataset_id)
            print(f"REAPED {dataset.dataset_id} (expires-at {dataset.labels.get('expires-at')})")
    return {"deleted": deleted, "today": today.isoformat()}
