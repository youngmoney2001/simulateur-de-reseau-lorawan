// SPDX-License-Identifier: Apache-2.0
#include "lsim/lorawan_frame.hpp"

#include <cstring>

namespace lsim::lorawan {
namespace {

constexpr std::uint8_t kMajorLoRaWanR1 = 0;
constexpr std::uint8_t kMaxFPort = 223;  // 225..255 réservés, 224 = test

bool is_uplink(MType t) {
    return t == MType::UnconfirmedDataUp || t == MType::ConfirmedDataUp;
}

bool is_downlink(MType t) {
    return t == MType::UnconfirmedDataDown || t == MType::ConfirmedDataDown;
}

bool is_data(MType t) {
    return is_uplink(t) || is_downlink(t);
}

// Vérifie la cohérence logique d'une trame avant encodage.
FrameStatus check_consistency(const DataFrame& f) {
    if (!is_data(f.mtype)) {
        return FrameStatus::NotADataFrame;
    }
    if (f.fopts_len > kMaxFOpts || f.frm_payload_len > kMaxFrmPayload) {
        return FrameStatus::FieldOutOfRange;
    }
    if (!f.has_fport && f.frm_payload_len != 0) {
        return FrameStatus::FieldOutOfRange;  // FRMPayload exige un FPort
    }
    if (f.has_fport && f.fport > kMaxFPort) {
        return FrameStatus::FieldOutOfRange;
    }
    if (f.has_fport && f.fport == 0 && f.fopts_len != 0) {
        return FrameStatus::FieldOutOfRange;  // FOpts interdit avec FPort 0
    }
    // Les bits de FCtrl dépendent du sens : refuser ceux qui ne s'appliquent pas.
    if (is_uplink(f.mtype) && f.f_pending) {
        return FrameStatus::FieldOutOfRange;
    }
    if (is_downlink(f.mtype) && (f.adr_ack_req || f.class_b)) {
        return FrameStatus::FieldOutOfRange;
    }
    const std::size_t total = kMinDataFrame + f.fopts_len + (f.has_fport ? 1u : 0u) + f.frm_payload_len;
    if (total > kMaxPhyPayload) {
        return FrameStatus::FieldOutOfRange;
    }
    return FrameStatus::Ok;
}

}  // namespace

std::size_t encoded_size(const DataFrame& f) {
    if (check_consistency(f) != FrameStatus::Ok) {
        return 0;
    }
    return kMinDataFrame + f.fopts_len + (f.has_fport ? 1u : 0u) + f.frm_payload_len;
}

FrameStatus encode(const DataFrame& f, std::uint8_t* out, std::size_t cap, std::size_t& out_written) {
    out_written = 0;
    const FrameStatus cons = check_consistency(f);
    if (cons != FrameStatus::Ok) {
        return cons;
    }
    if (out == nullptr) {
        return FrameStatus::BufferTooSmall;
    }
    const std::size_t total = encoded_size(f);
    if (cap < total) {
        return FrameStatus::BufferTooSmall;
    }

    std::size_t p = 0;
    // MHDR : MType sur 3 bits de poids fort, RFU = 0, Major = 0.
    out[p++] = static_cast<std::uint8_t>((static_cast<std::uint8_t>(f.mtype) << 5) | kMajorLoRaWanR1);

    // DevAddr en little-endian.
    out[p++] = static_cast<std::uint8_t>(f.dev_addr & 0xFFu);
    out[p++] = static_cast<std::uint8_t>((f.dev_addr >> 8) & 0xFFu);
    out[p++] = static_cast<std::uint8_t>((f.dev_addr >> 16) & 0xFFu);
    out[p++] = static_cast<std::uint8_t>((f.dev_addr >> 24) & 0xFFu);

    // FCtrl.
    std::uint8_t fctrl = static_cast<std::uint8_t>(f.fopts_len & 0x0Fu);
    if (f.adr) {
        fctrl |= 0x80u;
    }
    if (f.ack) {
        fctrl |= 0x20u;
    }
    if (is_uplink(f.mtype)) {
        if (f.adr_ack_req) {
            fctrl |= 0x40u;
        }
        if (f.class_b) {
            fctrl |= 0x10u;
        }
    } else if (f.f_pending) {
        fctrl |= 0x10u;
    }
    out[p++] = fctrl;

    // FCnt en little-endian (16 bits de poids faible).
    out[p++] = static_cast<std::uint8_t>(f.fcnt & 0xFFu);
    out[p++] = static_cast<std::uint8_t>((f.fcnt >> 8) & 0xFFu);

    // FOpts.
    for (std::uint8_t i = 0; i < f.fopts_len; ++i) {
        out[p++] = f.fopts[i];
    }

    // FPort et FRMPayload.
    if (f.has_fport) {
        out[p++] = f.fport;
        if (f.frm_payload_len > 0) {
            std::memcpy(out + p, f.frm_payload.data(), f.frm_payload_len);
            p += f.frm_payload_len;
        }
    }

    // MIC transporté tel quel (le calcul relève du module crypto).
    std::memcpy(out + p, f.mic.data(), kMicSize);
    p += kMicSize;

    out_written = p;
    return FrameStatus::Ok;
}

FrameStatus decode(const std::uint8_t* in, std::size_t len, DataFrame& out) {
    out = DataFrame{};
    if (in == nullptr || len < kMinDataFrame || len > kMaxPhyPayload) {
        return FrameStatus::MalformedFrame;
    }

    const std::uint8_t mhdr = in[0];
    const std::uint8_t major = mhdr & 0x03u;
    const std::uint8_t rfu = (mhdr >> 2) & 0x07u;
    const auto mtype = static_cast<MType>(mhdr >> 5);
    if (major != kMajorLoRaWanR1) {
        return FrameStatus::UnsupportedMajorVersion;
    }
    if (!is_data(mtype)) {
        return FrameStatus::NotADataFrame;
    }
    if (rfu != 0) {
        return FrameStatus::MalformedFrame;
    }
    out.mtype = mtype;

    out.dev_addr = static_cast<std::uint32_t>(in[1]) | (static_cast<std::uint32_t>(in[2]) << 8) |
                   (static_cast<std::uint32_t>(in[3]) << 16) | (static_cast<std::uint32_t>(in[4]) << 24);

    const std::uint8_t fctrl = in[5];
    out.adr = (fctrl & 0x80u) != 0;
    out.ack = (fctrl & 0x20u) != 0;
    if (is_uplink(mtype)) {
        out.adr_ack_req = (fctrl & 0x40u) != 0;
        out.class_b = (fctrl & 0x10u) != 0;
    } else {
        // Bit 6 réservé (RFU) en downlink : doit valoir 0. Le rejeter garantit
        // un encodage canonique unique par trame (pas de malléabilité).
        if ((fctrl & 0x40u) != 0) {
            return FrameStatus::MalformedFrame;
        }
        out.f_pending = (fctrl & 0x10u) != 0;
    }
    out.fopts_len = static_cast<std::uint8_t>(fctrl & 0x0Fu);

    out.fcnt = static_cast<std::uint16_t>(in[6] | (static_cast<std::uint16_t>(in[7]) << 8));

    // Position après FHDR. Le MIC (4 octets) termine toujours la trame.
    const std::size_t fopts_start = 8;
    const std::size_t body_start = fopts_start + out.fopts_len;
    if (body_start + kMicSize > len) {
        return FrameStatus::MalformedFrame;  // FOptsLen incohérent avec la taille
    }
    std::memcpy(out.fopts.data(), in + fopts_start, out.fopts_len);

    const std::size_t body_end = len - kMicSize;
    if (body_start < body_end) {
        const std::uint8_t fport = in[body_start];
        if (fport > kMaxFPort) {
            return FrameStatus::FieldOutOfRange;
        }
        if (fport == 0 && out.fopts_len != 0) {
            return FrameStatus::MalformedFrame;
        }
        out.has_fport = true;
        out.fport = fport;
        const std::size_t payload_len = body_end - body_start - 1;
        if (payload_len > kMaxFrmPayload) {
            return FrameStatus::MalformedFrame;
        }
        out.frm_payload_len = static_cast<std::uint8_t>(payload_len);
        std::memcpy(out.frm_payload.data(), in + body_start + 1, payload_len);
    }

    std::memcpy(out.mic.data(), in + body_end, kMicSize);
    return FrameStatus::Ok;
}

}  // namespace lsim::lorawan
