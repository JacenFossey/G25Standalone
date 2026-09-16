#define DIRECTINPUT_VERSION 0x0800
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <dinput.h>
#include <dinputd.h>

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <limits>
#include <mutex>
#include <new>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

#pragma comment(lib, "ws2_32.lib")

namespace {

// {F1571E1D-B59D-4322-BAC1-EBD860FA40D7}
constexpr CLSID kClassId{
    0xf1571e1d, 0xb59d, 0x4322,
    {0xba, 0xc1, 0xeb, 0xd8, 0x60, 0xfa, 0x40, 0xd7}
};
constexpr IID kEffectDriverIid{
    0x02538130, 0x898f, 0x11d0,
    {0x9a, 0xd0, 0x00, 0xa0, 0xc9, 0xa0, 0x6e, 0x35}
};

constexpr DWORD kConstant = 0;
constexpr DWORD kRamp = 1;
constexpr DWORD kSquare = 2;
constexpr DWORD kSine = 3;
constexpr DWORD kTriangle = 4;
constexpr DWORD kSawUp = 5;
constexpr DWORD kSawDown = 6;
constexpr DWORD kSpring = 7;
constexpr DWORD kDamper = 8;
constexpr DWORD kInertia = 9;
constexpr DWORD kFriction = 10;
constexpr DWORD kCustom = 11;

std::atomic<long> g_live_objects{};
std::atomic<long> g_server_locks{};

class Bridge {
public:
    Bridge() = default;
    ~Bridge() { close(); }

    bool send_line(const std::string& line) {
        std::lock_guard lock(mutex_);
        if (!ensure_connected()) return false;
        std::string payload = line;
        payload.push_back('\n');
        if (send_all(payload)) return true;

        close_unlocked();
        if (!ensure_connected()) return false;
        if (send_all(payload)) return true;
        close_unlocked();
        return false;
    }

private:
    bool ensure_connected() {
        if (socket_ != INVALID_SOCKET) return true;

        static std::once_flag winsock_once;
        static bool winsock_ok = false;
        std::call_once(winsock_once, [] {
            WSADATA data{};
            winsock_ok = WSAStartup(MAKEWORD(2, 2), &data) == 0;
        });
        if (!winsock_ok) return false;

        SOCKET sock = ::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
        if (sock == INVALID_SOCKET) return false;

        sockaddr_in address{};
        address.sin_family = AF_INET;
        address.sin_port = htons(26726);
        inet_pton(AF_INET, "127.0.0.1", &address.sin_addr);

        if (::connect(sock, reinterpret_cast<sockaddr*>(&address), sizeof(address)) == SOCKET_ERROR) {
            closesocket(sock);
            return false;
        }

        socket_ = sock;
        return true;
    }

    bool send_all(const std::string& payload) {
        std::size_t sent = 0;
        while (sent < payload.size()) {
            int rc = ::send(
                socket_,
                payload.data() + sent,
                static_cast<int>(payload.size() - sent),
                0
            );
            if (rc == SOCKET_ERROR || rc == 0) return false;
            sent += static_cast<std::size_t>(rc);
        }
        return true;
    }

    void close() {
        std::lock_guard lock(mutex_);
        close_unlocked();
    }

    void close_unlocked() {
        if (socket_ != INVALID_SOCKET) {
            shutdown(socket_, SD_BOTH);
            closesocket(socket_);
            socket_ = INVALID_SOCKET;
        }
    }

    std::mutex mutex_;
    SOCKET socket_ = INVALID_SOCKET;
};

struct EffectRecord {
    DWORD kind{};
    bool playing{};
};

std::string command_name(DWORD command) {
    switch (command) {
    case DISFFC_RESET: return "reset";
    case DISFFC_STOPALL: return "stopall";
    case DISFFC_PAUSE: return "pause";
    case DISFFC_CONTINUE: return "continue";
    case DISFFC_SETACTUATORSON: return "actuators_on";
    case DISFFC_SETACTUATORSOFF: return "actuators_off";
    default: return {};
    }
}

class EffectDriver final : public IDirectInputEffectDriver {
public:
    EffectDriver() { ++g_live_objects; }
    ~EffectDriver() override {
        end_device();
        --g_live_objects;
    }

    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** object) override {
        if (!object) return E_POINTER;
        *object = nullptr;
        if (IsEqualIID(iid, IID_IUnknown) || IsEqualIID(iid, kEffectDriverIid)) {
            *object = static_cast<IDirectInputEffectDriver*>(this);
            AddRef();
            return S_OK;
        }
        return E_NOINTERFACE;
    }

    ULONG STDMETHODCALLTYPE AddRef() override {
        return static_cast<ULONG>(++refs_);
    }

    ULONG STDMETHODCALLTYPE Release() override {
        const auto value = --refs_;
        if (!value) delete this;
        return static_cast<ULONG>(value);
    }

    HRESULT STDMETHODCALLTYPE DeviceID(
        DWORD version,
        DWORD external_id,
        DWORD begin,
        DWORD,
        LPVOID init_data
    ) override {
        if (version < 0x0500) return DIERR_UNSUPPORTED;

        std::lock_guard lock(state_mutex_);
        if (!begin) {
            if (active_ && external_id == external_id_) {
                send_device(false);
                active_ = false;
                effects_.clear();
            }
            return S_OK;
        }

        if (!init_data) return E_POINTER;
        const auto* init = static_cast<const DIHIDFFINITINFO*>(init_data);
        if (init->dwSize != sizeof(DIHIDFFINITINFO)) return E_INVALIDARG;

        active_ = true;
        external_id_ = external_id;
        next_handle_ = 0;
        effects_.clear();
        device_gain_ = DI_FFNOMINALMAX;
        actuators_ = true;
        paused_ = false;
        stopped_ = true;
        send_device(true);
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE GetVersions(LPDIDRIVERVERSIONS versions) override {
        if (!versions) return E_POINTER;
        if (versions->dwSize != sizeof(DIDRIVERVERSIONS)) return E_INVALIDARG;
        versions->dwFirmwareRevision = 0x1222;
        versions->dwHardwareRevision = 0x1222;
        versions->dwFFDriverVersion = 0x00010000;
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE Escape(DWORD, DWORD, LPDIEFFESCAPE) override {
        return E_NOTIMPL;
    }

    HRESULT STDMETHODCALLTYPE SetGain(DWORD external_id, DWORD gain) override {
        std::lock_guard lock(state_mutex_);
        if (!valid(external_id)) return DIERR_NOTINITIALIZED;
        const DWORD bounded = std::min(gain, DWORD{DI_FFNOMINALMAX});
        device_gain_ = bounded;
        std::ostringstream json;
        json << "{\"op\":\"gain\",\"value\":" << bounded << "}";
        bridge_.send_line(json.str());
        return bounded == gain ? S_OK : DI_TRUNCATED;
    }

    HRESULT STDMETHODCALLTYPE SendForceFeedbackCommand(DWORD external_id, DWORD command) override {
        std::lock_guard lock(state_mutex_);
        if (!valid(external_id)) return DIERR_NOTINITIALIZED;
        const std::string name = command_name(command);
        if (name.empty()) return E_NOTIMPL;

        if (command == DISFFC_RESET) {
            effects_.clear();
            actuators_ = true;
            paused_ = false;
            stopped_ = true;
        } else if (command == DISFFC_STOPALL) {
            for (auto& [id, effect] : effects_) {
                (void)id;
                effect.playing = false;
            }
            paused_ = false;
            stopped_ = true;
        } else if (command == DISFFC_PAUSE) {
            paused_ = true;
        } else if (command == DISFFC_CONTINUE) {
            paused_ = false;
        } else if (command == DISFFC_SETACTUATORSON) {
            actuators_ = true;
        } else if (command == DISFFC_SETACTUATORSOFF) {
            actuators_ = false;
        }

        bridge_.send_line("{\"op\":\"command\",\"name\":\"" + name + "\"}");
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE GetForceFeedbackState(DWORD external_id, LPDIDEVICESTATE state) override {
        if (!state) return E_POINTER;
        if (state->dwSize != sizeof(DIDEVICESTATE)) return E_INVALIDARG;
        std::lock_guard lock(state_mutex_);
        if (!valid(external_id)) return DIERR_NOTINITIALIZED;

        state->dwState = DIGFFS_POWERON | DIGFFS_SAFETYSWITCHOFF | DIGFFS_USERFFSWITCHON;
        state->dwState |= effects_.empty() ? DIGFFS_EMPTY : 0;
        state->dwState |= stopped_ ? DIGFFS_STOPPED : 0;
        state->dwState |= paused_ ? DIGFFS_PAUSED : 0;
        state->dwState |= actuators_ ? DIGFFS_ACTUATORSON : DIGFFS_ACTUATORSOFF;
        state->dwLoad = static_cast<DWORD>(std::min<std::size_t>(100, effects_.size() * 2));
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE DownloadEffect(
        DWORD external_id,
        DWORD effect_type,
        LPDWORD handle,
        LPCDIEFFECT input,
        DWORD flags
    ) override {
        if (!handle || !input) return E_POINTER;
        if (effect_type > kCustom) return DIERR_UNSUPPORTED;
        if (input->dwSize < sizeof(DIEFFECT_DX5)) return E_INVALIDARG;
        if (input->cAxes != 1 || !input->rgdwAxes || !input->rglDirection) return DIERR_INVALIDPARAM;
        if ((input->dwFlags & DIEFF_POLAR) || (input->dwFlags & DIEFF_SPHERICAL)) return DIERR_UNSUPPORTED;
        if (input->lpEnvelope && input->lpEnvelope->dwSize != sizeof(DIENVELOPE)) return E_INVALIDARG;

        std::lock_guard lock(state_mutex_);
        if (!valid(external_id)) return DIERR_NOTINITIALIZED;

        if (*handle == 0) {
            if (effects_.size() >= 64) return DIERR_DEVICEFULL;
            do { ++next_handle_; } while (!next_handle_ || effects_.contains(next_handle_));
            *handle = next_handle_;
            effects_[*handle] = EffectRecord{effect_type, false};
        } else if (!effects_.contains(*handle)) {
            return DIERR_NOTDOWNLOADED;
        } else {
            effects_[*handle].kind = effect_type;
        }

        if (flags & DIEP_NODOWNLOAD) return S_OK;

        std::ostringstream json;
        json << "{\"op\":\"effect\",\"id\":" << *handle
             << ",\"kind\":" << effect_type
             << ",\"duration\":" << input->dwDuration
             << ",\"gain\":" << std::min(input->dwGain, DWORD{DI_FFNOMINALMAX})
             << ",\"delay\":" << (input->dwSize >= sizeof(DIEFFECT) ? input->dwStartDelay : 0)
             << ",\"direction\":" << (input->rglDirection[0] < 0 ? -1 : 1);

        if (input->lpEnvelope) {
            const auto& env = *input->lpEnvelope;
            json << ",\"envelope\":{\"attackLevel\":" << env.dwAttackLevel
                 << ",\"attackTime\":" << env.dwAttackTime
                 << ",\"fadeLevel\":" << env.dwFadeLevel
                 << ",\"fadeTime\":" << env.dwFadeTime << "}";
        }

        if (!append_type_specific(json, effect_type, input)) return DIERR_INVALIDPARAM;

        const bool start = (flags & DIEP_START) != 0;
        json << ",\"start\":" << (start ? "true" : "false") << "}";
        bridge_.send_line(json.str());

        if (start) {
            effects_[*handle].playing = true;
            stopped_ = false;
        }
        return input->dwGain <= DI_FFNOMINALMAX ? S_OK : DI_TRUNCATED;
    }

    HRESULT STDMETHODCALLTYPE DestroyEffect(DWORD external_id, DWORD handle) override {
        std::lock_guard lock(state_mutex_);
        if (!valid(external_id)) return DIERR_NOTINITIALIZED;
        if (!effects_.erase(handle)) return DIERR_NOTDOWNLOADED;
        std::ostringstream json;
        json << "{\"op\":\"destroy\",\"id\":" << handle << "}";
        bridge_.send_line(json.str());
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE StartEffect(DWORD external_id, DWORD handle, DWORD mode, DWORD count) override {
        std::lock_guard lock(state_mutex_);
        if (!valid(external_id)) return DIERR_NOTINITIALIZED;
        auto found = effects_.find(handle);
        if (found == effects_.end()) return DIERR_NOTDOWNLOADED;

        const bool solo = (mode & DIES_SOLO) != 0;
        if (solo) {
            for (auto& [id, effect] : effects_) {
                if (id != handle) effect.playing = false;
            }
        }
        found->second.playing = true;
        stopped_ = false;

        std::ostringstream json;
        json << "{\"op\":\"start\",\"id\":" << handle
             << ",\"iterations\":" << (count ? count : 1)
             << ",\"solo\":" << (solo ? "true" : "false") << "}";
        bridge_.send_line(json.str());
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE StopEffect(DWORD external_id, DWORD handle) override {
        std::lock_guard lock(state_mutex_);
        if (!valid(external_id)) return DIERR_NOTINITIALIZED;
        auto found = effects_.find(handle);
        if (found == effects_.end()) return DIERR_NOTDOWNLOADED;
        found->second.playing = false;
        std::ostringstream json;
        json << "{\"op\":\"stop\",\"id\":" << handle << "}";
        bridge_.send_line(json.str());
        return S_OK;
    }

    HRESULT STDMETHODCALLTYPE GetEffectStatus(DWORD external_id, DWORD handle, LPDWORD status) override {
        if (!status) return E_POINTER;
        std::lock_guard lock(state_mutex_);
        if (!valid(external_id)) return DIERR_NOTINITIALIZED;
        const auto found = effects_.find(handle);
        if (found == effects_.end()) return DIERR_NOTDOWNLOADED;
        *status = found->second.playing ? DIEGES_PLAYING : 0;
        return S_OK;
    }

private:
    bool valid(DWORD external_id) const {
        return active_ && external_id == external_id_;
    }

    void send_device(bool begin) {
        std::ostringstream json;
        json << "{\"op\":\"device\",\"device\":" << external_id_
             << ",\"begin\":" << (begin ? "true" : "false") << "}";
        bridge_.send_line(json.str());
    }

    void end_device() {
        std::lock_guard lock(state_mutex_);
        if (active_) send_device(false);
        active_ = false;
        effects_.clear();
    }

    static bool append_type_specific(
        std::ostringstream& json,
        DWORD kind,
        LPCDIEFFECT input
    ) {
        if (!input->lpvTypeSpecificParams) return false;

        if (kind == kConstant) {
            if (input->cbTypeSpecificParams < sizeof(DICONSTANTFORCE)) return false;
            const auto& value = *static_cast<const DICONSTANTFORCE*>(input->lpvTypeSpecificParams);
            json << ",\"magnitude\":" << std::clamp(value.lMagnitude, -LONG{DI_FFNOMINALMAX}, LONG{DI_FFNOMINALMAX});
            return true;
        }
        if (kind == kRamp) {
            if (input->cbTypeSpecificParams < sizeof(DIRAMPFORCE)) return false;
            const auto& value = *static_cast<const DIRAMPFORCE*>(input->lpvTypeSpecificParams);
            json << ",\"rampStart\":" << std::clamp(value.lStart, -LONG{DI_FFNOMINALMAX}, LONG{DI_FFNOMINALMAX})
                 << ",\"rampEnd\":" << std::clamp(value.lEnd, -LONG{DI_FFNOMINALMAX}, LONG{DI_FFNOMINALMAX});
            return true;
        }
        if (kind >= kSquare && kind <= kSawDown) {
            if (input->cbTypeSpecificParams < sizeof(DIPERIODIC)) return false;
            const auto& value = *static_cast<const DIPERIODIC*>(input->lpvTypeSpecificParams);
            if (!value.dwPeriod) return false;
            json << ",\"magnitude\":" << std::min(value.dwMagnitude, DWORD{DI_FFNOMINALMAX})
                 << ",\"offset\":" << std::clamp(value.lOffset, -LONG{DI_FFNOMINALMAX}, LONG{DI_FFNOMINALMAX})
                 << ",\"phase\":" << (value.dwPhase % (360 * DI_DEGREES))
                 << ",\"period\":" << value.dwPeriod;
            return true;
        }
        if (kind >= kSpring && kind <= kFriction) {
            if (input->cbTypeSpecificParams < sizeof(DICONDITION)) return false;
            const auto& value = static_cast<const DICONDITION*>(input->lpvTypeSpecificParams)[0];
            json << ",\"condition\":{\"offset\":" << std::clamp(value.lOffset, -LONG{DI_FFNOMINALMAX}, LONG{DI_FFNOMINALMAX})
                 << ",\"positiveCoefficient\":" << std::clamp(value.lPositiveCoefficient, -LONG{DI_FFNOMINALMAX}, LONG{DI_FFNOMINALMAX})
                 << ",\"negativeCoefficient\":" << std::clamp(value.lNegativeCoefficient, -LONG{DI_FFNOMINALMAX}, LONG{DI_FFNOMINALMAX})
                 << ",\"positiveSaturation\":" << std::min(value.dwPositiveSaturation, DWORD{DI_FFNOMINALMAX})
                 << ",\"negativeSaturation\":" << std::min(value.dwNegativeSaturation, DWORD{DI_FFNOMINALMAX})
                 << ",\"deadband\":" << std::clamp(value.lDeadBand, LONG{0}, LONG{DI_FFNOMINALMAX * 2}) << "}";
            return true;
        }
        if (kind == kCustom) {
            if (input->cbTypeSpecificParams < sizeof(DICUSTOMFORCE)) return false;
            const auto& value = *static_cast<const DICUSTOMFORCE*>(input->lpvTypeSpecificParams);
            if (value.cChannels != 1 || !value.dwSamplePeriod || !value.cSamples || !value.rglForceData) return false;
            if (value.cSamples > 65536) return false;
            json << ",\"samplePeriod\":" << value.dwSamplePeriod << ",\"samples\":[";
            for (DWORD i = 0; i < value.cSamples; ++i) {
                if (i) json << ',';
                json << std::clamp(value.rglForceData[i], -LONG{DI_FFNOMINALMAX}, LONG{DI_FFNOMINALMAX});
            }
            json << ']';
            return true;
        }
        return false;
    }

    std::atomic<long> refs_{1};
    std::mutex state_mutex_;
    Bridge bridge_;
    std::unordered_map<DWORD, EffectRecord> effects_;
    DWORD external_id_ = std::numeric_limits<DWORD>::max();
    DWORD next_handle_ = 0;
    DWORD device_gain_ = DI_FFNOMINALMAX;
    bool active_ = false;
    bool stopped_ = true;
    bool paused_ = false;
    bool actuators_ = true;
};

class ClassFactory final : public IClassFactory {
public:
    ClassFactory() { ++g_live_objects; }
    ~ClassFactory() override { --g_live_objects; }

    HRESULT STDMETHODCALLTYPE QueryInterface(REFIID iid, void** object) override {
        if (!object) return E_POINTER;
        *object = nullptr;
        if (IsEqualIID(iid, IID_IUnknown) || IsEqualIID(iid, IID_IClassFactory)) {
            *object = static_cast<IClassFactory*>(this);
            AddRef();
            return S_OK;
        }
        return E_NOINTERFACE;
    }

    ULONG STDMETHODCALLTYPE AddRef() override { return static_cast<ULONG>(++refs_); }
    ULONG STDMETHODCALLTYPE Release() override {
        const auto value = --refs_;
        if (!value) delete this;
        return static_cast<ULONG>(value);
    }

    HRESULT STDMETHODCALLTYPE CreateInstance(IUnknown* outer, REFIID iid, void** object) override {
        if (outer) return CLASS_E_NOAGGREGATION;
        if (!object) return E_POINTER;
        auto* driver = new (std::nothrow) EffectDriver();
        if (!driver) return E_OUTOFMEMORY;
        const HRESULT result = driver->QueryInterface(iid, object);
        driver->Release();
        return result;
    }

    HRESULT STDMETHODCALLTYPE LockServer(BOOL lock) override {
        if (lock) ++g_server_locks;
        else --g_server_locks;
        return S_OK;
    }

private:
    std::atomic<long> refs_{1};
};

} // namespace

extern "C" HRESULT __stdcall DllGetClassObject(REFCLSID clsid, REFIID iid, void** object) {
    if (!object) return E_POINTER;
    *object = nullptr;
    if (!IsEqualCLSID(clsid, kClassId)) return CLASS_E_CLASSNOTAVAILABLE;
    auto* factory = new (std::nothrow) ClassFactory();
    if (!factory) return E_OUTOFMEMORY;
    const HRESULT result = factory->QueryInterface(iid, object);
    factory->Release();
    return result;
}

extern "C" HRESULT __stdcall DllCanUnloadNow() {
    return g_live_objects.load() == 0 && g_server_locks.load() == 0 ? S_OK : S_FALSE;
}
