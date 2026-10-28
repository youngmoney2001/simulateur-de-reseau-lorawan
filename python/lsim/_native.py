"""Chargement de la bibliothèque native lsim et déclaration des prototypes C.

Chaque prototype est déclaré explicitement (types et arguments) : aucun appel
implicite avec des types par défaut, ce qui évite les troncatures silencieuses.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path


class _CRadioConfig(ctypes.Structure):
    _fields_ = [
        ("spreading_factor", ctypes.c_uint8),
        ("bandwidth_hz", ctypes.c_uint32),
        ("coding_rate", ctypes.c_uint8),
        ("preamble_symbols", ctypes.c_uint16),
        ("crc_on", ctypes.c_uint8),
        ("explicit_header", ctypes.c_uint8),
        ("low_data_rate_optimize", ctypes.c_uint8),
    ]


class _CJoinKeys(ctypes.Structure):
    _fields_ = [
        ("js_enc_key", ctypes.c_uint8 * 16),
        ("js_int_key", ctypes.c_uint8 * 16),
    ]


class _CSessionKeys11(ctypes.Structure):
    _fields_ = [
        ("f_nwk_s_int_key", ctypes.c_uint8 * 16),
        ("s_nwk_s_int_key", ctypes.c_uint8 * 16),
        ("nwk_s_enc_key", ctypes.c_uint8 * 16),
        ("app_s_key", ctypes.c_uint8 * 16),
    ]


class _CMacCommand(ctypes.Structure):
    _fields_ = [
        ("kind", ctypes.c_uint8),
        ("margin", ctypes.c_uint8),
        ("gw_cnt", ctypes.c_uint8),
        ("data_rate", ctypes.c_uint8),
        ("tx_power", ctypes.c_uint8),
        ("ch_mask", ctypes.c_uint16),
        ("ch_mask_cntl", ctypes.c_uint8),
        ("nb_trans", ctypes.c_uint8),
        ("ack_channel_mask", ctypes.c_uint8),
        ("ack_data_rate", ctypes.c_uint8),
        ("ack_power", ctypes.c_uint8),
        ("max_dcycle", ctypes.c_uint8),
        ("battery", ctypes.c_uint8),
        ("dev_margin", ctypes.c_int8),
        ("lorawan_minor", ctypes.c_uint8),
        ("rx2_data_rate", ctypes.c_uint8),
        ("rx1_dr_offset", ctypes.c_uint8),
        ("freq_100hz", ctypes.c_uint32),
        ("ch_index", ctypes.c_uint8),
        ("min_dr", ctypes.c_uint8),
        ("max_dr", ctypes.c_uint8),
        ("ack_rx_channel", ctypes.c_uint8),
        ("ack_rx2_data_rate", ctypes.c_uint8),
        ("ack_rx1_dr_offset", ctypes.c_uint8),
        ("ack_dr_range", ctypes.c_uint8),
        ("ack_channel_freq", ctypes.c_uint8),
        ("rx_delay", ctypes.c_uint8),
        ("device_time_s", ctypes.c_uint32),
        ("device_time_frac", ctypes.c_uint8),
        ("rejoin_period", ctypes.c_uint8),
        ("rejoin_max_retries", ctypes.c_uint8),
        ("rejoin_type", ctypes.c_uint8),
        ("max_time_n", ctypes.c_uint8),
        ("max_count_n", ctypes.c_uint8),
        ("ack_time_ok", ctypes.c_uint8),
        ("ack_uplink_freq_exists", ctypes.c_uint8),
        ("adr_limit_exp", ctypes.c_uint8),
        ("adr_delay_exp", ctypes.c_uint8),
        ("ping_periodicity", ctypes.c_uint8),
        ("ack_beacon_freq", ctypes.c_uint8),
    ]


class _CAdrInput(ctypes.Structure):
    _fields_ = [
        ("snr_tenth_db", ctypes.c_int32 * 20),
        ("n_samples", ctypes.c_uint8),
        ("dr", ctypes.c_uint8),
        ("dr_sf", ctypes.c_uint8 * 16),
        ("min_dr", ctypes.c_uint8),
        ("max_dr", ctypes.c_uint8),
        ("tx_power_index", ctypes.c_uint8),
        ("max_tx_power_index", ctypes.c_uint8),
        ("power_step_tenth_db", ctypes.c_int32),
        ("installation_margin_tenth_db", ctypes.c_int32),
    ]


class _CAdrOutput(ctypes.Structure):
    _fields_ = [
        ("dr", ctypes.c_uint8),
        ("tx_power_index", ctypes.c_uint8),
    ]


class _CAdrDeviceState(ctypes.Structure):
    _fields_ = [
        ("ack_cnt", ctypes.c_uint64),
        ("dr", ctypes.c_uint8),
        ("min_dr", ctypes.c_uint8),
        ("tx_power_index", ctypes.c_uint8),
        ("default_tx_power_index", ctypes.c_uint8),
        ("channels_subset", ctypes.c_uint8),
    ]


class _CAdrUplinkOutcome(ctypes.Structure):
    _fields_ = [
        ("ack_req", ctypes.c_uint8),
        ("default_channels_reenabled", ctypes.c_uint8),
    ]


class _CRekeyDevice(ctypes.Structure):
    _fields_ = [("state", ctypes.c_uint8), ("uplinks", ctypes.c_uint64)]


class _CRekeyServer(ctypes.Structure):
    _fields_ = [("awaiting", ctypes.c_uint8)]


class _CSessionKeys(ctypes.Structure):
    _fields_ = [
        ("f_nwk_s_int_key", ctypes.c_uint8 * 16),
        ("s_nwk_s_int_key", ctypes.c_uint8 * 16),
        ("nwk_s_enc_key", ctypes.c_uint8 * 16),
        ("app_s_key", ctypes.c_uint8 * 16),
    ]


class _CSessionUplinkPlan(ctypes.Structure):
    _fields_ = [
        ("fcnt32", ctypes.c_uint32),
        ("rekey_ind", ctypes.c_uint8),
        ("ack_req", ctypes.c_uint8),
        ("default_channels_reenabled", ctypes.c_uint8),
    ]


class _CSessionUplinkEnd(ctypes.Structure):
    _fields_ = [("state", ctypes.c_uint8)]


class _CClassBDevice(ctypes.Structure):
    _fields_ = [
        ("synchronized", ctypes.c_uint8),
        ("last_beacon_rx_ns", ctypes.c_uint64),
        ("last_beacon_time_s", ctypes.c_uint32),
        ("dev_addr", ctypes.c_uint32),
        ("periodicity", ctypes.c_uint8),
        ("clock_drift_ppm", ctypes.c_uint32),
    ]


class _CClassBGatewayInfo(ctypes.Structure):
    _fields_ = [
        ("time_s", ctypes.c_uint32),
        ("present", ctypes.c_uint8),
        ("info_desc", ctypes.c_uint8),
        ("has_coordinates", ctypes.c_uint8),
        ("latitude_deg", ctypes.c_double),
        ("longitude_deg", ctypes.c_double),
    ]


class _CClassBPingSlot(ctypes.Structure):
    _fields_ = [
        ("start_ns", ctypes.c_uint64),
        ("slot_index", ctypes.c_uint32),
        ("beacon_time_s", ctypes.c_uint32),
        ("beacon_period_start_ns", ctypes.c_uint64),
        ("window_half_ns", ctypes.c_uint64),
    ]


class _CSessionInfo(ctypes.Structure):
    _fields_ = [
        ("state", ctypes.c_uint8),
        ("dev_addr", ctypes.c_uint32),
        ("fcnt_up", ctypes.c_uint64),
        ("nf_cnt_dwn", ctypes.c_uint64),
        ("af_cnt_dwn", ctypes.c_uint64),
        ("dr", ctypes.c_uint8),
        ("tx_power_index", ctypes.c_uint8),
        ("ack_cnt", ctypes.c_uint64),
        ("cycle_open", ctypes.c_uint8),
    ]


class _CUplinkFrame(ctypes.Structure):
    _fields_ = [
        ("dev_addr", ctypes.c_uint32),
        ("mtype", ctypes.c_uint8),
        ("adr", ctypes.c_uint8),
        ("adr_ack_req", ctypes.c_uint8),
        ("ack", ctypes.c_uint8),
        ("class_b", ctypes.c_uint8),
        ("fcnt", ctypes.c_uint16),
        ("has_fport", ctypes.c_uint8),
        ("fport", ctypes.c_uint8),
        ("payload_len", ctypes.c_uint8),
        ("payload", ctypes.c_uint8 * 242),
        ("mic", ctypes.c_uint8 * 4),
        ("fopts_len", ctypes.c_uint8),
        ("fopts", ctypes.c_uint8 * 15),
    ]


class _CUplinkContext(ctypes.Structure):
    _fields_ = [
        ("conf_fcnt", ctypes.c_uint16),
        ("tx_dr", ctypes.c_uint8),
        ("tx_ch", ctypes.c_uint8),
        ("fcnt32", ctypes.c_uint32),
    ]


class _CDownlinkContext(ctypes.Structure):
    _fields_ = [
        ("conf_fcnt", ctypes.c_uint16),
        ("nfcnt32", ctypes.c_uint32),
        ("afcnt32", ctypes.c_uint32),
    ]


class _CEndDevice(ctypes.Structure):
    _fields_ = [
        ("x_m", ctypes.c_double),
        ("y_m", ctypes.c_double),
        ("spreading_factor", ctypes.c_uint8),
        ("payload_bytes", ctypes.c_uint32),
        ("tx_power_dbm", ctypes.c_double),
        ("start_offset_ns", ctypes.c_int64),
        ("period_ns", ctypes.c_int64),
        ("messages", ctypes.c_uint32),
        ("duty_cycle", ctypes.c_double),
    ]


class _CGateway(ctypes.Structure):
    _fields_ = [
        ("x_m", ctypes.c_double),
        ("y_m", ctypes.c_double),
        ("antenna_gain_dbi", ctypes.c_double),
    ]


class _CPropagation(ctypes.Structure):
    _fields_ = [
        ("frequency_hz", ctypes.c_double),
        ("reference_distance_m", ctypes.c_double),
        ("exponent", ctypes.c_double),
        ("capture_threshold_db", ctypes.c_double),
        ("shadowing_sigma_db", ctypes.c_double),
        ("shadowing_seed", ctypes.c_uint64),
    ]


class _CDeviceStats(ctypes.Structure):
    _fields_ = [
        ("sent", ctypes.c_uint64),
        ("received", ctypes.c_uint64),
        ("lost_sensitivity", ctypes.c_uint64),
        ("lost_collision", ctypes.c_uint64),
        ("airtime_ns", ctypes.c_uint64),
    ]


class _CDownlinkPlan(ctypes.Structure):
    _fields_ = [
        ("device_class", ctypes.c_uint8),
        ("count", ctypes.c_uint32),
        ("first_request_ns", ctypes.c_int64),
        ("request_period_ns", ctypes.c_int64),
        ("rx_window_ns", ctypes.c_int64),
        ("dev_addr", ctypes.c_uint32),
        ("periodicity", ctypes.c_uint8),
        ("clock_drift_ppm", ctypes.c_uint32),
    ]


class _CDownlinkStats(ctypes.Structure):
    _fields_ = [
        ("requested", ctypes.c_uint64),
        ("delivered", ctypes.c_uint64),
        ("latency_sum_ns", ctypes.c_uint64),
        ("latency_max_ns", ctypes.c_uint64),
    ]


class _CSimStats(ctypes.Structure):
    _fields_ = [
        ("sent", ctypes.c_uint64),
        ("received", ctypes.c_uint64),
        ("lost_sensitivity", ctypes.c_uint64),
        ("lost_collision", ctypes.c_uint64),
        ("airtime_ns", ctypes.c_uint64),
        ("gateway_busy_ns", ctypes.c_uint64),
        ("gateway_peak_concurrent", ctypes.c_uint64),
        ("observation_ns", ctypes.c_int64),
        ("gateway_utilization", ctypes.c_double),
    ]


class _CJoinRequest(ctypes.Structure):
    _fields_ = [
        ("join_eui", ctypes.c_uint8 * 8),
        ("dev_eui", ctypes.c_uint8 * 8),
        ("dev_nonce", ctypes.c_uint8 * 2),
    ]


class _CJoinAccept(ctypes.Structure):
    _fields_ = [
        ("join_nonce", ctypes.c_uint8 * 3),
        ("net_id", ctypes.c_uint8 * 3),
        ("dev_addr", ctypes.c_uint32),
        ("dl_settings", ctypes.c_uint8),
        ("rx_delay", ctypes.c_uint8),
        ("has_cflist", ctypes.c_uint8),
        ("cflist", ctypes.c_uint8 * 16),
    ]


class _CObstacle(ctypes.Structure):
    _fields_ = [
        ("x_min_m", ctypes.c_double),
        ("y_min_m", ctypes.c_double),
        ("x_max_m", ctypes.c_double),
        ("y_max_m", ctypes.c_double),
        ("height_m", ctypes.c_double),
        ("attenuation_db", ctypes.c_double),
    ]


class _CEnvironment(ctypes.Structure):
    _fields_ = [
        ("grid_z", ctypes.POINTER(ctypes.c_float)),
        ("grid_nx", ctypes.c_uint32),
        ("grid_ny", ctypes.c_uint32),
        ("grid_origin_x_m", ctypes.c_double),
        ("grid_origin_y_m", ctypes.c_double),
        ("grid_cell_m", ctypes.c_double),
        ("obstacles", ctypes.POINTER(_CObstacle)),
        ("obstacle_count", ctypes.c_size_t),
        ("gateway_height_m", ctypes.c_double),
        ("device_height_m", ctypes.c_double),
    ]




def _load_library() -> ctypes.CDLL:
    """Charge la bibliothèque native. Chemin surchargeable via LSIM_LIBRARY."""
    override = os.environ.get("LSIM_LIBRARY")
    candidates = [Path(override)] if override else []
    root = Path(__file__).resolve().parents[2]
    candidates += [
        root / "build" / "liblsim_core.so",
        root / "build" / "liblsim_core.dylib",
        root / "build" / "Release" / "lsim_core.dll",
    ]
    for path in candidates:
        if path.is_file():
            lib = ctypes.CDLL(str(path))
            break
    else:
        raise OSError(
            "bibliothèque native lsim introuvable : compilez le cœur "
            "(cmake -S . -B build && cmake --build build) ou définissez LSIM_LIBRARY"
        )

    lib.lsim_version.restype = ctypes.c_uint32
    lib.lsim_version.argtypes = []
    lib.lsim_time_on_air_ns.restype = ctypes.c_int32
    lib.lsim_time_on_air_ns.argtypes = [
        ctypes.POINTER(_CRadioConfig),
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_int64),
    ]
    return lib


_DBL = ctypes.POINTER(ctypes.c_double)
_U8P = ctypes.POINTER(ctypes.c_uint8)

LIB = _load_library()

LIB.lsim_receiver_sensitivity_dbm.restype = ctypes.c_int32
LIB.lsim_receiver_sensitivity_dbm.argtypes = [ctypes.c_uint8, ctypes.c_uint32, _DBL]
LIB.lsim_free_space_path_loss_db.restype = ctypes.c_int32
LIB.lsim_free_space_path_loss_db.argtypes = [ctypes.c_double, ctypes.c_double, _DBL]
LIB.lsim_log_distance_path_loss_db.restype = ctypes.c_int32
LIB.lsim_log_distance_path_loss_db.argtypes = [
    ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double, _DBL]
LIB.lsim_max_allowable_path_loss_db.restype = ctypes.c_int32
LIB.lsim_max_allowable_path_loss_db.argtypes = [ctypes.c_double] * 6 + [_DBL]
LIB.lsim_max_range_m.restype = ctypes.c_int32
LIB.lsim_max_range_m.argtypes = [ctypes.c_double, ctypes.c_double, ctypes.c_double, ctypes.c_double, _DBL]

LIB.lsim_derive_join_keys.restype = ctypes.c_int32
LIB.lsim_derive_join_keys.argtypes = [_U8P, _U8P, ctypes.POINTER(_CJoinKeys)]
LIB.lsim_derive_session_keys_11.restype = ctypes.c_int32
LIB.lsim_derive_session_keys_11.argtypes = [
    _U8P, _U8P, _U8P, _U8P, _U8P, ctypes.POINTER(_CSessionKeys11)]
LIB.lsim_seal_uplink.restype = ctypes.c_int32
LIB.lsim_seal_uplink.argtypes = [
    ctypes.POINTER(_CUplinkFrame), ctypes.POINTER(_CSessionKeys11),
    ctypes.POINTER(_CUplinkContext), _U8P, ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t)]
LIB.lsim_open_uplink.restype = ctypes.c_int32
LIB.lsim_open_uplink.argtypes = [
    _U8P, ctypes.c_size_t, ctypes.POINTER(_CSessionKeys11),
    ctypes.POINTER(_CUplinkContext), ctypes.POINTER(_CUplinkFrame)]
LIB.lsim_seal_downlink.restype = ctypes.c_int32
LIB.lsim_seal_downlink.argtypes = [
    ctypes.POINTER(_CUplinkFrame), ctypes.POINTER(_CSessionKeys11),
    ctypes.POINTER(_CDownlinkContext), _U8P, ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t)]
LIB.lsim_open_downlink.restype = ctypes.c_int32
LIB.lsim_open_downlink.argtypes = [
    _U8P, ctypes.c_size_t, ctypes.POINTER(_CSessionKeys11),
    ctypes.POINTER(_CDownlinkContext), ctypes.POINTER(_CUplinkFrame)]
LIB.lsim_simulate_uplinks.restype = ctypes.c_int32
LIB.lsim_simulate_uplinks.argtypes = [
    ctypes.POINTER(_CEndDevice), ctypes.c_size_t, ctypes.POINTER(_CGateway),
    ctypes.POINTER(_CPropagation), ctypes.POINTER(_CDeviceStats),
    ctypes.POINTER(_CSimStats)]
LIB.lsim_simulate_uplinks_env.restype = ctypes.c_int32
LIB.lsim_simulate_uplinks_env.argtypes = [
    ctypes.POINTER(_CEndDevice), ctypes.c_size_t, ctypes.POINTER(_CGateway),
    ctypes.POINTER(_CPropagation), ctypes.POINTER(_CEnvironment),
    ctypes.POINTER(_CDeviceStats), ctypes.POINTER(_CSimStats)]
LIB.lsim_simulate_downlinks_env.restype = ctypes.c_int32
LIB.lsim_simulate_downlinks_env.argtypes = [
    ctypes.POINTER(_CEndDevice), ctypes.POINTER(_CDownlinkPlan), ctypes.c_size_t,
    ctypes.POINTER(_CGateway), ctypes.POINTER(_CPropagation), ctypes.POINTER(_CEnvironment),
    ctypes.POINTER(_CDeviceStats), ctypes.POINTER(_CSimStats),
    ctypes.POINTER(_CDownlinkStats), ctypes.POINTER(_CDownlinkStats)]
LIB.lsim_coverage_radii.restype = ctypes.c_int32
LIB.lsim_coverage_radii.argtypes = [
    ctypes.POINTER(_CGateway), ctypes.POINTER(_CPropagation), ctypes.c_double,
    ctypes.POINTER(_CEnvironment), ctypes.c_double, ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_double)]
LIB.lsim_encode_join_request.restype = ctypes.c_int32
LIB.lsim_encode_join_request.argtypes = [
    ctypes.POINTER(_CJoinRequest), _U8P, _U8P]
LIB.lsim_decode_join_request.restype = ctypes.c_int32
LIB.lsim_decode_join_request.argtypes = [
    _U8P, ctypes.c_size_t, _U8P, ctypes.POINTER(_CJoinRequest)]
LIB.lsim_encode_join_accept.restype = ctypes.c_int32
LIB.lsim_encode_join_accept.argtypes = [
    ctypes.POINTER(_CJoinAccept), _U8P, _U8P, _U8P, _U8P, _U8P, ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t)]
LIB.lsim_decode_join_accept.restype = ctypes.c_int32
LIB.lsim_decode_join_accept.argtypes = [
    _U8P, ctypes.c_size_t, _U8P, _U8P, _U8P, _U8P, ctypes.POINTER(_CJoinAccept)]
LIB.lsim_mac_encode.restype = ctypes.c_int32
LIB.lsim_mac_encode.argtypes = [
    ctypes.POINTER(_CMacCommand), _U8P, ctypes.POINTER(ctypes.c_size_t)]
LIB.lsim_mac_decode.restype = ctypes.c_int32
LIB.lsim_mac_decode.argtypes = [
    _U8P, ctypes.c_size_t, ctypes.c_uint8, ctypes.POINTER(_CMacCommand),
    ctypes.POINTER(ctypes.c_size_t)]
LIB.lsim_mac_append_fopts.restype = ctypes.c_int32
LIB.lsim_mac_append_fopts.argtypes = [
    _U8P, ctypes.POINTER(ctypes.c_uint8), _U8P, ctypes.c_size_t]
class _CRejoin02(ctypes.Structure):
    _fields_ = [
        ("rejoin_type", ctypes.c_uint8),
        ("net_id", ctypes.c_uint8 * 3),
        ("dev_eui", ctypes.c_uint8 * 8),
        ("rjcount0", ctypes.c_uint16),
    ]


class _CRejoin1(ctypes.Structure):
    _fields_ = [
        ("join_eui", ctypes.c_uint8 * 8),
        ("dev_eui", ctypes.c_uint8 * 8),
        ("rjcount1", ctypes.c_uint16),
    ]


LIB.lsim_rejoin_encode_02.restype = ctypes.c_int32
LIB.lsim_rejoin_encode_02.argtypes = [ctypes.POINTER(_CRejoin02), _U8P, _U8P]
LIB.lsim_rejoin_decode_02.restype = ctypes.c_int32
LIB.lsim_rejoin_decode_02.argtypes = [_U8P, ctypes.c_size_t, _U8P, ctypes.POINTER(_CRejoin02)]
LIB.lsim_rejoin_encode_1.restype = ctypes.c_int32
LIB.lsim_rejoin_encode_1.argtypes = [ctypes.POINTER(_CRejoin1), _U8P, _U8P]
LIB.lsim_rejoin_decode_1.restype = ctypes.c_int32
LIB.lsim_rejoin_decode_1.argtypes = [_U8P, ctypes.c_size_t, _U8P, ctypes.POINTER(_CRejoin1)]
LIB.lsim_registry_create.restype = ctypes.c_int32
LIB.lsim_registry_create.argtypes = [ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64)]
LIB.lsim_registry_destroy.restype = ctypes.c_int32
LIB.lsim_registry_destroy.argtypes = [ctypes.c_uint64]
LIB.lsim_registry_accept_join_request.restype = ctypes.c_int32
LIB.lsim_registry_accept_join_request.argtypes = [
    ctypes.c_uint64, _U8P, ctypes.c_size_t, _U8P, ctypes.POINTER(_CJoinRequest)]
LIB.lsim_registry_accept_rejoin_02.restype = ctypes.c_int32
LIB.lsim_registry_accept_rejoin_02.argtypes = [
    ctypes.c_uint64, _U8P, ctypes.c_size_t, _U8P, ctypes.POINTER(_CRejoin02)]
LIB.lsim_registry_accept_rejoin_1.restype = ctypes.c_int32
LIB.lsim_registry_accept_rejoin_1.argtypes = [
    ctypes.c_uint64, _U8P, ctypes.c_size_t, _U8P, ctypes.POINTER(_CRejoin1)]
LIB.lsim_registry_on_join_accepted.restype = ctypes.c_int32
LIB.lsim_registry_on_join_accepted.argtypes = [ctypes.c_uint64, _U8P]
LIB.lsim_registry_device_count.restype = ctypes.c_int32
LIB.lsim_registry_device_count.argtypes = [ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64)]
LIB.lsim_adr_device_uplink.restype = ctypes.c_int32
LIB.lsim_adr_device_uplink.argtypes = [
    ctypes.POINTER(_CAdrDeviceState), ctypes.c_uint8, ctypes.c_uint8, ctypes.POINTER(_CAdrUplinkOutcome)]
LIB.lsim_adr_device_downlink.restype = ctypes.c_int32
LIB.lsim_adr_device_downlink.argtypes = [ctypes.POINTER(_CAdrDeviceState)]
LIB.lsim_rekey_device_join_accepted.restype = ctypes.c_int32
LIB.lsim_rekey_device_join_accepted.argtypes = [ctypes.POINTER(_CRekeyDevice)]
LIB.lsim_rekey_device_uplink_completed.restype = ctypes.c_int32
LIB.lsim_rekey_device_uplink_completed.argtypes = [
    ctypes.POINTER(_CRekeyDevice), ctypes.c_uint64, ctypes.c_uint8, ctypes.c_uint8]
LIB.lsim_rekey_device_must_send_rekey_ind.restype = ctypes.c_int32
LIB.lsim_rekey_device_must_send_rekey_ind.argtypes = [ctypes.POINTER(_CRekeyDevice), _U8P]
LIB.lsim_rekey_server_join_accepted.restype = ctypes.c_int32
LIB.lsim_rekey_server_join_accepted.argtypes = [ctypes.POINTER(_CRekeyServer)]
LIB.lsim_session_create.restype = ctypes.c_int32
LIB.lsim_session_create.argtypes = [ctypes.POINTER(ctypes.c_uint64)]
LIB.lsim_session_destroy.restype = ctypes.c_int32
LIB.lsim_session_destroy.argtypes = [ctypes.c_uint64]
LIB.lsim_session_join_accepted.restype = ctypes.c_int32
LIB.lsim_session_join_accepted.argtypes = [
    ctypes.c_uint64, ctypes.POINTER(_CSessionKeys), ctypes.c_uint32, ctypes.c_uint8,
    ctypes.c_uint8, ctypes.c_uint8, ctypes.c_uint8]
LIB.lsim_session_begin_uplink.restype = ctypes.c_int32
LIB.lsim_session_begin_uplink.argtypes = [
    ctypes.c_uint64, ctypes.c_uint8, ctypes.c_uint8, ctypes.POINTER(_CSessionUplinkPlan)]
LIB.lsim_session_receive_downlink.restype = ctypes.c_int32
LIB.lsim_session_receive_downlink.argtypes = [
    ctypes.c_uint64, ctypes.c_uint8, ctypes.c_uint32, ctypes.c_uint8, ctypes.c_uint8]
LIB.lsim_session_end_uplink.restype = ctypes.c_int32
LIB.lsim_session_end_uplink.argtypes = [ctypes.c_uint64, ctypes.POINTER(_CSessionUplinkEnd)]
LIB.lsim_classb_decode_beacon.restype = ctypes.c_int32
LIB.lsim_classb_decode_beacon.argtypes = [_U8P, ctypes.c_size_t, ctypes.c_uint8, ctypes.POINTER(ctypes.c_uint32)]
LIB.lsim_classb_decode_beacon_full.restype = ctypes.c_int32
LIB.lsim_classb_decode_beacon_full.argtypes = [
    _U8P, ctypes.c_size_t, ctypes.c_uint8, ctypes.c_uint8, ctypes.POINTER(_CClassBGatewayInfo)]
LIB.lsim_classb_us902_channel.restype = ctypes.c_int32
LIB.lsim_classb_us902_channel.argtypes = [
    ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint32)]
LIB.lsim_classb_ping_offset.restype = ctypes.c_int32
LIB.lsim_classb_ping_offset.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint8, ctypes.POINTER(ctypes.c_uint32)]
LIB.lsim_classb_on_beacon.restype = ctypes.c_int32
LIB.lsim_classb_on_beacon.argtypes = [ctypes.POINTER(_CClassBDevice), ctypes.c_uint64, ctypes.c_uint32]
LIB.lsim_classb_beacon_state.restype = ctypes.c_int32
LIB.lsim_classb_beacon_state.argtypes = [ctypes.POINTER(_CClassBDevice), ctypes.c_uint64, _U8P]
LIB.lsim_classb_next_ping_slot.restype = ctypes.c_int32
LIB.lsim_classb_next_ping_slot.argtypes = [ctypes.POINTER(_CClassBDevice), ctypes.c_uint64, ctypes.POINTER(_CClassBPingSlot)]
LIB.lsim_session_snapshot.restype = ctypes.c_int32
LIB.lsim_session_snapshot.argtypes = [ctypes.c_uint64, ctypes.POINTER(_CSessionInfo)]
LIB.lsim_rekey_server_on_uplink.restype = ctypes.c_int32
LIB.lsim_rekey_server_on_uplink.argtypes = [
    ctypes.POINTER(_CRekeyServer), ctypes.c_uint8, ctypes.c_uint8, _U8P]
LIB.lsim_adr_decide.restype = ctypes.c_int32
LIB.lsim_adr_decide.argtypes = [ctypes.POINTER(_CAdrInput), ctypes.POINTER(_CAdrOutput)]
LIB.lsim_registry_export.restype = ctypes.c_int32
LIB.lsim_registry_export.argtypes = [
    ctypes.c_uint64, _U8P, _U8P, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
LIB.lsim_registry_import.restype = ctypes.c_int32
LIB.lsim_registry_import.argtypes = [_U8P, _U8P, ctypes.c_size_t, ctypes.POINTER(ctypes.c_uint64)]
