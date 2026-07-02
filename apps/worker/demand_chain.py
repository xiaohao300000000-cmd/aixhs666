from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from intelligence.demand_chain import DemandEventChain, DemandTextRecord, build_demand_event_chains
from intelligence.demand_chain.chain import demand_record_from_mapping


def build_worker_demand_event_chains(records: Iterable[DemandTextRecord | dict[str, Any]]) -> list[DemandEventChain]:
    normalized_records = [
        record if isinstance(record, DemandTextRecord) else demand_record_from_mapping(record)
        for record in records
    ]
    return build_demand_event_chains(normalized_records)
