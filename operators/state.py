from __future__ import annotations

from collections import defaultdict

from core.context import ConditionSet, StateObservation, StateSet, TimedValue


def _samples(entities):
    for entity in entities.items:
        if hasattr(entity, "history"):
            for sample in entity.history:
                yield entity.id, entity.id, sample
        else:
            yield (
                getattr(entity, "track_id", None) or entity.id,
                getattr(entity, "track_id", None),
                entity,
            )


def state_detect(inputs, params, services, node_id):
    mode = params["evidence_mode"]
    state_labels = params.get("state_labels", {})
    default_state = params["default_state"]
    observations = []

    for target_id, track_id, sample in _samples(inputs["entities"]):
        confidence = None
        if mode == "label":
            state = state_labels.get(sample.label, default_state)
        elif mode == "phrase":
            state = state_labels.get(getattr(sample, "phrase", None), default_state)
        elif mode == "aspect_ratio":
            x0, y0, x1, y1 = sample.bbox
            ratio = (x1 - x0) / max(y1 - y0, 1e-9)
            state = (
                params["positive_state"]
                if ratio >= float(params["threshold"])
                else default_state
            )
            confidence = ratio
        else:
            raise ValueError(f"unsupported evidence_mode: {mode}")

        observations.append(
            StateObservation(
                target_id=target_id,
                state=state,
                timestamp=sample.timestamp,
                frame_index=sample.frame_index,
                confidence=confidence,
                track_id=track_id,
                evidence_ids=[sample.id],
            )
        )
    return StateSet(observations)


def state_transition(inputs, params, services, node_id):
    grouped = defaultdict(list)
    for observation in inputs["states"].items:
        grouped[observation.track_id or observation.target_id].append(observation)

    values = []
    max_seconds = float(params["max_seconds"])
    consume_source = bool(params["consume_source"])
    for entity_id, observations in grouped.items():
        source = None
        for observation in sorted(observations, key=lambda item: item.timestamp):
            if observation.state == params["from_state"]:
                source = observation
            elif observation.state == params["to_state"] and source is not None:
                elapsed = observation.timestamp - source.timestamp
                if 0 <= elapsed <= max_seconds:
                    values.append(
                        TimedValue(
                            key=entity_id,
                            value=True,
                            timestamp=observation.timestamp,
                            frame_index=observation.frame_index,
                            metadata={
                                "from_state": source.state,
                                "to_state": observation.state,
                                "from_timestamp": source.timestamp,
                                "elapsed_seconds": elapsed,
                                "evidence_ids": source.evidence_ids
                                + observation.evidence_ids,
                            },
                        )
                    )
                    if consume_source:
                        source = None
    return ConditionSet(values)


__all__ = ["state_detect", "state_transition"]
