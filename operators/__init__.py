from .appearance import visual_color_fraction, visual_geometry
from .filtering import (
    filter_apply,
    objects_filter_by_label,
    objects_filter_by_phrase,
    tracks_filter,
    tracks_filter_by_events,
)
from .events import event_from_condition, event_relabel
from .logic import (
    logic_all,
    logic_any,
    logic_compare,
    logic_compare_heading_by_lane,
    logic_not,
)
from .measure import (
    measure_count,
    measure_heading,
    measure_lane_majority_heading,
    measure_majority_heading,
    measure_region_count,
    measure_region_speed,
    measure_speed,
)
from .media import media_image, media_video, video_sample
from .output import output_alert, output_draw
from .pairs import pairs_build, pairs_filter, pairs_measure
from .pattern import (
    event_trigger,
    temporal_absence,
    temporal_event_duration,
    temporal_join,
    temporal_qualify,
    temporal_repeat,
    temporal_sequence_v2,
)
from .perception import objects_deduplicate, rex_ground, rex_ground_raw
from .preprocess import image_resize, image_tile, object_crop
from .objects import objects_from_tracks, objects_merge, objects_relabel
from .region import (
    direction_image_axis,
    direction_manual,
    direction_manual_set,
    region_from_objects,
    region_full_frame,
    region_manual,
    region_manual_set,
    regions_merge,
)
from .spatial import spatial_associate, spatial_inside
from .sets import set_anti_join, set_difference, set_partition, set_semi_join
from .reduce import (
    reduce_all,
    reduce_count,
    reduce_exists,
    reduce_quantify,
    reduce_statistic,
)
from .result import evidence_collect, event_attach_evidence, result_project
from .state import state_detect, state_transition
from .temporal import temporal_hold, temporal_persist, temporal_sequence
from .tracking import track_confirm, track_iou


def build_default_implementations():
    return {
        "media.image@1.0": media_image,
        "media.video@1.0": media_video,
        "video.sample@1.0": video_sample,
        "video.sample@1.1": video_sample,
        "image.resize@1.0": image_resize,
        "image.resize@1.1": image_resize,
        "image.tile@1.0": image_tile,
        "image.tile@1.1": image_tile,
        "object.crop@1.0": object_crop,
        "rex.ground@1.0": rex_ground,
        "rex.ground@1.1": rex_ground_raw,
        "objects.deduplicate@1.0": objects_deduplicate,
        "objects.filter_by_phrase@1.0": objects_filter_by_phrase,
        "objects.filter_by_label@1.0": objects_filter_by_label,
        "objects.merge@1.0": objects_merge,
        "visual.color_fraction@1.0": visual_color_fraction,
        "visual.geometry@1.0": visual_geometry,
        "region.full_frame@1.0": region_full_frame,
        "region.manual@1.0": region_manual,
        "region.manual_set@1.0": region_manual_set,
        "region.from_objects@1.0": region_from_objects,
        "regions.merge@1.0": regions_merge,
        "direction.manual@1.0": direction_manual,
        "direction.manual_set@1.0": direction_manual_set,
        "direction.image_axis@1.0": direction_image_axis,
        "track.iou@1.0": track_iou,
        "track.confirm@1.0": track_confirm,
        "spatial.inside@1.0": spatial_inside,
        "spatial.associate@1.0": spatial_associate,
        "measure.count@1.0": measure_count,
        "measure.region_count@1.0": measure_region_count,
        "measure.region_speed@1.0": measure_region_speed,
        "measure.speed@1.0": measure_speed,
        "measure.heading@1.0": measure_heading,
        "measure.majority_heading@1.0": measure_majority_heading,
        "measure.lane_majority_heading@1.0": measure_lane_majority_heading,
        "logic.compare@1.0": logic_compare,
        "logic.heading_by_lane@1.0": logic_compare_heading_by_lane,
        "logic.all@1.0": logic_all,
        "logic.any@1.0": logic_any,
        "logic.not@1.0": logic_not,
        "filter.apply@1.0": filter_apply,
        "tracks.filter@1.0": tracks_filter,
        "tracks.filter_by_events@1.0": tracks_filter_by_events,
        "objects.from_tracks@1.0": objects_from_tracks,
        "objects.relabel@1.0": objects_relabel,
        "event.from_condition@1.0": event_from_condition,
        "event.relabel@1.0": event_relabel,
        "temporal.hold@1.0": temporal_hold,
        "temporal.persist@1.0": temporal_persist,
        "temporal.sequence@1.0": temporal_sequence,
        "temporal.join@1.0": temporal_join,
        "temporal.qualify@1.0": temporal_qualify,
        "temporal.event_duration@1.0": temporal_event_duration,
        "temporal.sequence@2.0": temporal_sequence_v2,
        "temporal.absence@1.0": temporal_absence,
        "temporal.repeat@1.0": temporal_repeat,
        "event.trigger@2.0": event_trigger,
        "output.draw@1.0": output_draw,
        "output.alert@1.0": output_alert,
        "set.partition@1.0": set_partition,
        "set.difference@1.0": set_difference,
        "set.semi_join@1.0": set_semi_join,
        "set.anti_join@1.0": set_anti_join,
        "pairs.build@1.0": pairs_build,
        "pairs.measure@1.0": pairs_measure,
        "pairs.filter@1.0": pairs_filter,
        "reduce.count@1.0": reduce_count,
        "reduce.exists@1.0": reduce_exists,
        "reduce.all@1.0": reduce_all,
        "reduce.statistic@1.0": reduce_statistic,
        "reduce.quantify@1.0": reduce_quantify,
        "evidence.collect@1.0": evidence_collect,
        "event.attach_evidence@1.0": event_attach_evidence,
        "result.project@1.0": result_project,
        "state.detect@1.0": state_detect,
        "state.transition@1.0": state_transition,
    }


__all__ = ["build_default_implementations"]
