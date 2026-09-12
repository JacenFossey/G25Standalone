#define DIRECTINPUT_VERSION 0x0800
#define INITGUID

#include <winsock2.h>
#include <ws2tcpip.h>

#include <windows.h>
#include <dinput.h>

#include <algorithm>
#include <cctype>
#include <cstdarg>
#include <cstdio>
#include <cwctype>
#include <string>
#include <type_traits>

#pragma comment(lib, "ws2_32.lib")

// Forward declaration
static void log_message(const char* format, ...);


// -----------------------------------------------------------------------------
// Globals / logging
// -----------------------------------------------------------------------------

static INIT_ONCE g_udp_init_once = INIT_ONCE_STATIC_INIT;
static SOCKET g_udp_socket = INVALID_SOCKET;
static sockaddr_in g_udp_target{};


static BOOL CALLBACK init_ffb_udp(
    PINIT_ONCE,
    PVOID,
    PVOID*
)
{
    WSADATA data{};

    if (WSAStartup(MAKEWORD(2, 2), &data) != 0)
    {
        log_message("FFB UDP: WSAStartup failed");
        return TRUE;
    }

    g_udp_socket = socket(
        AF_INET,
        SOCK_DGRAM,
        IPPROTO_UDP
    );

    if (g_udp_socket == INVALID_SOCKET)
    {
        log_message("FFB UDP: socket creation failed");
        return TRUE;
    }

    g_udp_target.sin_family = AF_INET;
    g_udp_target.sin_port = htons(26725);

    inet_pton(
        AF_INET,
        "127.0.0.1",
        &g_udp_target.sin_addr
    );

    log_message("FFB UDP bridge ready");

    return TRUE;
}


static void send_ffb_force(LONG magnitude)
{
    InitOnceExecuteOnce(
        &g_udp_init_once,
        init_ffb_udp,
        nullptr,
        nullptr
    );

    if (g_udp_socket == INVALID_SOCKET)
        return;

    magnitude = std::clamp<LONG>(
        magnitude,
        -10000,
        10000
    );

    // Python bridge expects network-byte-order signed int32.
    LONG packet =
        static_cast<LONG>(
            htonl(
                static_cast<ULONG>(magnitude)
            )
        );

    sendto(
        g_udp_socket,
        reinterpret_cast<const char*>(&packet),
        sizeof(packet),
        0,
        reinterpret_cast<const sockaddr*>(
            &g_udp_target
        ),
        sizeof(g_udp_target)
    );
}

static HMODULE g_module = nullptr;
static SRWLOCK g_log_lock = SRWLOCK_INIT;


// Synthetic "FFB driver" GUID presented to games.
// This does not correspond to an actual Windows driver.
DEFINE_GUID(
    GUID_G25StandaloneFF,
    0x7b76420d, 0x9d89, 0x4b53,
    0x88, 0xf9, 0x25, 0x67, 0xb8, 0xe1, 0x4a, 0x21
);

static bool is_diprop(REFGUID property, UINT_PTR id)
{
    // DirectInput DIPROP_* values are pseudo-GUIDs whose address
    // is the property ID, not actual GUID structures.
    return reinterpret_cast<UINT_PTR>(&property) == id;
}

static std::wstring log_path()
{
    wchar_t path[MAX_PATH]{};

    GetModuleFileNameW(
        g_module,
        path,
        static_cast<DWORD>(std::size(path))
    );

    wchar_t* slash = wcsrchr(path, L'\\');

    if (slash)
    {
        *(slash + 1) = L'\0';
        wcscat_s(path, L"g25_dinput8.log");
    }
    else
    {
        wcscpy_s(path, L"g25_dinput8.log");
    }

    return path;
}


static void log_message(const char* format, ...)
{
    char buffer[2048]{};

    va_list args;
    va_start(args, format);

    vsnprintf_s(
        buffer,
        sizeof(buffer),
        _TRUNCATE,
        format,
        args
    );

    va_end(args);

    std::string line = buffer;
    line += "\r\n";

    AcquireSRWLockExclusive(&g_log_lock);

    HANDLE file = CreateFileW(
        log_path().c_str(),
        FILE_APPEND_DATA,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        nullptr,
        OPEN_ALWAYS,
        FILE_ATTRIBUTE_NORMAL,
        nullptr
    );

    if (file != INVALID_HANDLE_VALUE)
    {
        DWORD written = 0;

        WriteFile(
            file,
            line.data(),
            static_cast<DWORD>(line.size()),
            &written,
            nullptr
        );

        CloseHandle(file);
    }

    ReleaseSRWLockExclusive(&g_log_lock);
}


// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------

static bool contains_g25(const char* text)
{
    if (!text)
        return false;

    std::string value(text);

    std::transform(
        value.begin(),
        value.end(),
        value.begin(),
        [](unsigned char c)
        {
            return static_cast<char>(std::tolower(c));
        }
    );

    return value.find("g25") != std::string::npos;
}


static bool contains_g25(const wchar_t* text)
{
    if (!text)
        return false;

    std::wstring value(text);

    std::transform(
        value.begin(),
        value.end(),
        value.begin(),
        [](wchar_t c)
        {
            return static_cast<wchar_t>(std::towlower(c));
        }
    );

    return value.find(L"g25") != std::wstring::npos;
}


// -----------------------------------------------------------------------------
// Fake Constant Force effect
//
// For this milestone it only records what the game asks for.
// It does NOT yet send torque to the wheel.
// -----------------------------------------------------------------------------

class FakeConstantForceEffect final : public IDirectInputEffect
{
public:
    FakeConstantForceEffect()
    {
        log_message("FakeConstantForceEffect created");
    }

    ~FakeConstantForceEffect()
    {
        send_ffb_force(0);
        log_message("FakeConstantForceEffect destroyed");
    }


    // IUnknown ---------------------------------------------------------------

    HRESULT STDMETHODCALLTYPE QueryInterface(
        REFIID riid,
        void** out
    ) override
    {
        if (!out)
            return E_POINTER;

        if (
            IsEqualGUID(riid, IID_IUnknown) ||
            IsEqualGUID(riid, IID_IDirectInputEffect)
        )
        {
            *out = static_cast<IDirectInputEffect*>(this);
            AddRef();
            return S_OK;
        }

        *out = nullptr;
        return E_NOINTERFACE;
    }


    ULONG STDMETHODCALLTYPE AddRef() override
    {
        return InterlockedIncrement(&ref_count_);
    }


    ULONG STDMETHODCALLTYPE Release() override
    {
        ULONG count = InterlockedDecrement(&ref_count_);

        if (count == 0)
            delete this;

        return count;
    }


    // IDirectInputEffect ------------------------------------------------------

    HRESULT STDMETHODCALLTYPE Initialize(
        HINSTANCE,
        DWORD,
        REFGUID
    ) override
    {
        return DI_OK;
    }


    HRESULT STDMETHODCALLTYPE GetEffectGuid(
        LPGUID guid
    ) override
    {
        if (!guid)
            return E_POINTER;

        *guid = GUID_ConstantForce;
        return DI_OK;
    }


    HRESULT STDMETHODCALLTYPE GetParameters(
        LPDIEFFECT effect,
        DWORD flags
    ) override
    {
        if (!effect)
            return E_POINTER;

        if (flags & DIEP_GAIN)
            effect->dwGain = gain_;

        if (
            (flags & DIEP_TYPESPECIFICPARAMS) &&
            effect->lpvTypeSpecificParams &&
            effect->cbTypeSpecificParams >= sizeof(DICONSTANTFORCE)
        )
        {
            auto* force =
                static_cast<DICONSTANTFORCE*>(
                    effect->lpvTypeSpecificParams
                );

            force->lMagnitude = magnitude_;
        }

        return DI_OK;
    }


    HRESULT STDMETHODCALLTYPE SetParameters(
        LPCDIEFFECT effect,
        DWORD flags
    ) override
    {
        if (!effect)
            return E_POINTER;

        if (flags & DIEP_GAIN)
            gain_ = effect->dwGain;

        // During CreateEffect, games sometimes provide initial parameters
        // without the exact DIEP flags we expect, so inspect the type-specific
        // block whenever it is valid.
        if (
            effect->lpvTypeSpecificParams &&
            effect->cbTypeSpecificParams >= sizeof(DICONSTANTFORCE)
        )
        {
            const auto* force =
                static_cast<const DICONSTANTFORCE*>(
                    effect->lpvTypeSpecificParams
                );

            magnitude_ = force->lMagnitude;
        }

        LONG direction = 0;

        if (
            effect->cAxes > 0 &&
            effect->rglDirection
        )
        {
            direction = effect->rglDirection[0];
        }

        // Games may update force parameters every frame. Keep the diagnostic
        // useful without opening and appending to the log file at frame rate.
        ULONGLONG now = GetTickCount64();

        if (now - last_parameter_log_ms_ >= 1000)
        {
            log_message(
                "Effect SetParameters: magnitude=%ld gain=%lu axes=%lu direction=%ld flags=0x%08lX",
                magnitude_,
                gain_,
                effect->cAxes,
                direction,
                flags
            );

            last_parameter_log_ms_ = now;
        }

        if (flags & DIEP_START)
        {
            playing_ = true;

            log_message(
                "Effect started via DIEP_START: magnitude=%ld",
                magnitude_
            );
        }

        if (playing_)
        {
            send_ffb_force(magnitude_);
        }

        return DI_OK;
    }


    HRESULT STDMETHODCALLTYPE Start(
        DWORD iterations,
        DWORD flags
    ) override
    {
        playing_ = true;

        log_message(
            "Effect Start: magnitude=%ld gain=%lu iterations=%lu flags=0x%08lX",
            magnitude_,
            gain_,
            iterations,
            flags
        );

         send_ffb_force(magnitude_);

        return DI_OK;
    }


    HRESULT STDMETHODCALLTYPE Stop() override
    {
        playing_ = false;

        send_ffb_force(0);

        log_message("Effect Stop");

        return DI_OK;
    }


    HRESULT STDMETHODCALLTYPE GetEffectStatus(
        LPDWORD status
    ) override
    {
        if (!status)
            return E_POINTER;

        *status = playing_ ? DIEGES_PLAYING : 0;

        return DI_OK;
    }


    HRESULT STDMETHODCALLTYPE Download() override
    {
        log_message("Effect Download");
        return DI_OK;
    }


    HRESULT STDMETHODCALLTYPE Unload() override
    {
        playing_ = false;

        send_ffb_force(0);

        log_message("Effect Unload");

        return DI_OK;
    }


    HRESULT STDMETHODCALLTYPE Escape(
        LPDIEFFESCAPE
    ) override
    {
        return DIERR_UNSUPPORTED;
    }


private:
    volatile LONG ref_count_ = 1;

    LONG magnitude_ = 0;
    DWORD gain_ = DI_FFNOMINALMAX;

    bool playing_ = false;
    ULONGLONG last_parameter_log_ms_ = 0;
};


// -----------------------------------------------------------------------------
// Object enumeration bridge
//
// The real generic HID device does not mark its X axis as an FFB actuator.
// We add DIDOI_FFACTUATOR to the steering axis.
// -----------------------------------------------------------------------------

struct ObjectContextA
{
    LPDIENUMDEVICEOBJECTSCALLBACKA callback;
    LPVOID user;
    bool actuator_only;
};


struct ObjectContextW
{
    LPDIENUMDEVICEOBJECTSCALLBACKW callback;
    LPVOID user;
    bool actuator_only;
};


static BOOL CALLBACK object_callback_a(
    LPCDIDEVICEOBJECTINSTANCEA object,
    LPVOID context_ptr
)
{
    auto* context =
        static_cast<ObjectContextA*>(context_ptr);

    DIDEVICEOBJECTINSTANCEA copy = *object;

    bool steering =
        IsEqualGUID(copy.guidType, GUID_XAxis);

    if (steering)
        copy.dwFlags |= DIDOI_FFACTUATOR;

    if (context->actuator_only && !steering)
        return DIENUM_CONTINUE;

    return context->callback(
        &copy,
        context->user
    );
}


static BOOL CALLBACK object_callback_w(
    LPCDIDEVICEOBJECTINSTANCEW object,
    LPVOID context_ptr
)
{
    auto* context =
        static_cast<ObjectContextW*>(context_ptr);

    DIDEVICEOBJECTINSTANCEW copy = *object;

    bool steering =
        IsEqualGUID(copy.guidType, GUID_XAxis);

    if (steering)
        copy.dwFlags |= DIDOI_FFACTUATOR;

    if (context->actuator_only && !steering)
        return DIENUM_CONTINUE;

    return context->callback(
        &copy,
        context->user
    );
}


// -----------------------------------------------------------------------------
// Device wrapper
// -----------------------------------------------------------------------------

template<bool Unicode>
class G25DeviceProxy final
    : public std::conditional_t<
        Unicode,
        IDirectInputDevice8W,
        IDirectInputDevice8A
    >
{
public:
    using Base =
        std::conditional_t<
            Unicode,
            IDirectInputDevice8W,
            IDirectInputDevice8A
        >;

    using Char =
        std::conditional_t<
            Unicode,
            wchar_t,
            char
        >;

    using DeviceInstance =
        std::conditional_t<
            Unicode,
            DIDEVICEINSTANCEW,
            DIDEVICEINSTANCEA
        >;

    using ObjectInstance =
        std::conditional_t<
            Unicode,
            DIDEVICEOBJECTINSTANCEW,
            DIDEVICEOBJECTINSTANCEA
        >;

    using EffectInfo =
        std::conditional_t<
            Unicode,
            DIEFFECTINFOW,
            DIEFFECTINFOA
        >;

    using ActionFormat =
        std::conditional_t<
            Unicode,
            DIACTIONFORMATW,
            DIACTIONFORMATA
        >;

    using ImageInfo =
        std::conditional_t<
            Unicode,
            DIDEVICEIMAGEINFOHEADERW,
            DIDEVICEIMAGEINFOHEADERA
        >;

    using EnumObjectCallback =
        std::conditional_t<
            Unicode,
            LPDIENUMDEVICEOBJECTSCALLBACKW,
            LPDIENUMDEVICEOBJECTSCALLBACKA
        >;

    using EnumEffectCallback =
        std::conditional_t<
            Unicode,
            LPDIENUMEFFECTSCALLBACKW,
            LPDIENUMEFFECTSCALLBACKA
        >;


    explicit G25DeviceProxy(Base* real)
        : real_(real)
    {
        log_message(
            "G25DeviceProxy created (%s)",
            Unicode ? "Unicode" : "ANSI"
        );
    }


    ~G25DeviceProxy()
    {
        if (real_)
            real_->Release();

        log_message("G25DeviceProxy destroyed");
    }


    // IUnknown ---------------------------------------------------------------

    HRESULT STDMETHODCALLTYPE QueryInterface(
        REFIID riid,
        void** out
    ) override
    {
        if (!out)
            return E_POINTER;

        bool supported =
            IsEqualGUID(riid, IID_IUnknown);

        if constexpr (Unicode)
            supported |= IsEqualGUID(riid, IID_IDirectInputDevice8W);
        else
            supported |= IsEqualGUID(riid, IID_IDirectInputDevice8A);

        if (supported)
        {
            *out = static_cast<Base*>(this);
            AddRef();
            return S_OK;
        }

        return real_->QueryInterface(
            riid,
            out
        );
    }


    ULONG STDMETHODCALLTYPE AddRef() override
    {
        return InterlockedIncrement(&ref_count_);
    }


    ULONG STDMETHODCALLTYPE Release() override
    {
        ULONG count =
            InterlockedDecrement(&ref_count_);

        if (count == 0)
            delete this;

        return count;
    }


    // Capabilities -----------------------------------------------------------

    HRESULT STDMETHODCALLTYPE GetCapabilities(
        LPDIDEVCAPS caps
    ) override
    {
        if (!caps)
            return E_POINTER;

        const DWORD caller_size = caps->dwSize;

        log_message(
            "GetCapabilities: caller dwSize=%lu",
            caller_size
        );

        HRESULT hr =
            real_->GetCapabilities(caps);

        if (SUCCEEDED(hr))
        {
            // dwFlags exists in both the legacy DX3 structure
            // and the modern structure.
            caps->dwFlags |= DIDC_FORCEFEEDBACK;

            // Only write the newer fields if the caller actually
            // supplied the full modern DIDEVCAPS structure.
            if (caller_size >= sizeof(DIDEVCAPS))
            {
                caps->dwFFSamplePeriod = 1000;
                caps->dwFFMinTimeResolution = 1000;
                caps->dwFFDriverVersion = 0x00010000;

                log_message(
                    "GetCapabilities: full structure; advertising FFB timing fields"
                );
            }
            else
            {
                log_message(
                    "GetCapabilities: legacy structure; advertising FFB flag only"
                );
            }
        }

        return hr;
    }


    HRESULT STDMETHODCALLTYPE EnumObjects(
        EnumObjectCallback callback,
        LPVOID user,
        DWORD flags
    ) override
    {
        log_message(
            "EnumObjects flags=0x%08lX",
            flags
        );

        if (!callback)
            return DIERR_INVALIDPARAM;

        bool actuator_only =
            (flags & DIDFT_FFACTUATOR) != 0;

        DWORD real_flags =
            actuator_only
                ? DIDFT_AXIS
                : flags;

        if constexpr (Unicode)
        {
            ObjectContextW context{
                callback,
                user,
                actuator_only
            };

            return real_->EnumObjects(
                object_callback_w,
                &context,
                real_flags
            );
        }
        else
        {
            ObjectContextA context{
                callback,
                user,
                actuator_only
            };

            return real_->EnumObjects(
                object_callback_a,
                &context,
                real_flags
            );
        }
    }


    HRESULT STDMETHODCALLTYPE GetObjectInfo(
        ObjectInstance* info,
        DWORD object,
        DWORD how
    ) override
    {
        HRESULT hr =
            real_->GetObjectInfo(
                info,
                object,
                how
            );

        if (
            SUCCEEDED(hr) &&
            info &&
            IsEqualGUID(info->guidType, GUID_XAxis)
        )
        {
            info->dwFlags |= DIDOI_FFACTUATOR;
        }

        return hr;
    }


    // Properties -------------------------------------------------------------

    HRESULT STDMETHODCALLTYPE GetProperty(
        REFGUID property,
        LPDIPROPHEADER header
    ) override
    {
        if (!header)
            return E_POINTER;

        if (is_diprop(property, 7)) // DIPROP_FFGAIN
        {
            auto* value =
                reinterpret_cast<LPDIPROPDWORD>(header);

            value->dwData = ff_gain_;

            log_message("GetProperty: DIPROP_FFGAIN");

            return DI_OK;
        }

        if (is_diprop(property, 8)) // DIPROP_FFLOAD
        {
            auto* value =
                reinterpret_cast<LPDIPROPDWORD>(header);

            value->dwData = 0;

            log_message("GetProperty: DIPROP_FFLOAD");

            return DI_OK;
        }

        if (is_diprop(property, 9)) // DIPROP_AUTOCENTER
        {
            auto* value =
                reinterpret_cast<LPDIPROPDWORD>(header);

            value->dwData = autocenter_;

            log_message("GetProperty: DIPROP_AUTOCENTER");

            return DI_OK;
        }

        return real_->GetProperty(
            property,
            header
        );
    }


    HRESULT STDMETHODCALLTYPE SetProperty(
        REFGUID property,
        LPCDIPROPHEADER header
    ) override
    {
        if (!header)
            return E_POINTER;

        if (is_diprop(property, 7)) // DIPROP_FFGAIN
        {
            const auto* value =
                reinterpret_cast<const DIPROPDWORD*>(header);

            ff_gain_ = value->dwData;

            log_message(
                "SetProperty: DIPROP_FFGAIN = %lu",
                ff_gain_
            );

            return DI_OK;
        }

        if (is_diprop(property, 9)) // DIPROP_AUTOCENTER
        {
            const auto* value =
                reinterpret_cast<const DIPROPDWORD*>(header);

            autocenter_ = value->dwData;

            log_message(
                "SetProperty: DIPROP_AUTOCENTER = %lu",
                autocenter_
            );

            return DI_OK;
        }

        return real_->SetProperty(
            property,
            header
        );
    }


    // Input pass-through -----------------------------------------------------

    HRESULT STDMETHODCALLTYPE Acquire() override
    {
        HRESULT hr = real_->Acquire();

        log_message(
            "Acquire -> 0x%08lX",
            hr
        );

        return hr;
    }


    HRESULT STDMETHODCALLTYPE Unacquire() override
    {
        return real_->Unacquire();
    }


    HRESULT STDMETHODCALLTYPE GetDeviceState(
        DWORD size,
        LPVOID data
    ) override
    {
        return real_->GetDeviceState(
            size,
            data
        );
    }


    HRESULT STDMETHODCALLTYPE GetDeviceData(
        DWORD object_size,
        LPDIDEVICEOBJECTDATA data,
        LPDWORD count,
        DWORD flags
    ) override
    {
        return real_->GetDeviceData(
            object_size,
            data,
            count,
            flags
        );
    }


    HRESULT STDMETHODCALLTYPE SetEventNotification(
        HANDLE event
    ) override
    {
        return real_->SetEventNotification(event);
    }


    HRESULT STDMETHODCALLTYPE SetCooperativeLevel(
        HWND window,
        DWORD flags
    ) override
    {
        log_message(
            "SetCooperativeLevel flags=0x%08lX",
            flags
        );

        return real_->SetCooperativeLevel(
            window,
            flags
        );
    }


    HRESULT STDMETHODCALLTYPE GetDeviceInfo(
        DeviceInstance* info
    ) override
    {
        if (!info)
            return E_POINTER;

        const DWORD caller_size = info->dwSize;

        log_message(
            "GetDeviceInfo: caller dwSize=%lu",
            caller_size
        );

        HRESULT hr =
            real_->GetDeviceInfo(info);

        if (
            SUCCEEDED(hr) &&
            caller_size >= sizeof(DeviceInstance)
        )
        {
            info->guidFFDriver =
                GUID_G25StandaloneFF;
        }

        return hr;
    }

    HRESULT STDMETHODCALLTYPE SetDataFormat(
        LPCDIDATAFORMAT format
    ) override
    {
        log_message("SetDataFormat");

        return real_->SetDataFormat(format);
    }

    HRESULT STDMETHODCALLTYPE RunControlPanel(
        HWND owner,
        DWORD flags
    ) override
    {
        return real_->RunControlPanel(
            owner,
            flags
        );
    }


    HRESULT STDMETHODCALLTYPE Initialize(
        HINSTANCE instance,
        DWORD version,
        REFGUID guid
    ) override
    {
        return real_->Initialize(
            instance,
            version,
            guid
        );
    }


    // FFB --------------------------------------------------------------------

    HRESULT STDMETHODCALLTYPE CreateEffect(
        REFGUID guid,
        LPCDIEFFECT effect,
        LPDIRECTINPUTEFFECT* out,
        LPUNKNOWN outer
    ) override
    {
        if (!out)
            return E_POINTER;

        *out = nullptr;

        if (!IsEqualGUID(guid, GUID_ConstantForce))
        {
            log_message(
                "CreateEffect: unsupported GUID Data1=%08lX",
                guid.Data1
            );

            return DIERR_UNSUPPORTED;
        }

        if (outer)
            return CLASS_E_NOAGGREGATION;

        log_message("CreateEffect: GUID_ConstantForce");

        auto* fake =
            new FakeConstantForceEffect();

        if (effect)
            fake->SetParameters(effect, 0);

        *out = fake;

        return DI_OK;
    }


    HRESULT STDMETHODCALLTYPE EnumEffects(
        EnumEffectCallback callback,
        LPVOID user,
        DWORD effect_type
    ) override
    {
        if (!callback)
            return DIERR_INVALIDPARAM;

        if (
            effect_type != DIEFT_ALL &&
            effect_type != DIEFT_CONSTANTFORCE
        )
        {
            return DI_OK;
        }

        EffectInfo info{};
        info.dwSize = sizeof(info);

        fill_effect_info(info);

        log_message(
            "EnumEffects: advertising Constant Force"
        );

        callback(
            &info,
            user
        );

        return DI_OK;
    }


    HRESULT STDMETHODCALLTYPE GetEffectInfo(
        EffectInfo* info,
        REFGUID guid
    ) override
    {
        if (!info)
            return E_POINTER;

        if (!IsEqualGUID(guid, GUID_ConstantForce))
            return DIERR_UNSUPPORTED;

        fill_effect_info(*info);

        return DI_OK;
    }


    HRESULT STDMETHODCALLTYPE GetForceFeedbackState(
        LPDWORD state
    ) override
    {
        if (!state)
            return E_POINTER;

        *state =
            DIGFFS_POWERON |
            DIGFFS_ACTUATORSON;

        return DI_OK;
    }


    HRESULT STDMETHODCALLTYPE SendForceFeedbackCommand(
        DWORD flags
    ) override
    {
        log_message(
            "SendForceFeedbackCommand flags=0x%08lX",
            flags
        );

        return DI_OK;
    }


    HRESULT STDMETHODCALLTYPE EnumCreatedEffectObjects(
        LPDIENUMCREATEDEFFECTOBJECTSCALLBACK,
        LPVOID,
        DWORD
    ) override
    {
        // We do not need this for the first diagnostic milestone.
        return DI_OK;
    }


    HRESULT STDMETHODCALLTYPE Escape(
        LPDIEFFESCAPE escape
    ) override
    {
        return real_->Escape(escape);
    }


    HRESULT STDMETHODCALLTYPE Poll() override
    {
        return real_->Poll();
    }


    HRESULT STDMETHODCALLTYPE SendDeviceData(
        DWORD size,
        LPCDIDEVICEOBJECTDATA data,
        LPDWORD count,
        DWORD flags
    ) override
    {
        return real_->SendDeviceData(
            size,
            data,
            count,
            flags
        );
    }


    // DirectInput 8 ----------------------------------------------------------

    HRESULT STDMETHODCALLTYPE BuildActionMap(
        ActionFormat* format,
        const Char* username,
        DWORD flags
    ) override
    {
        return real_->BuildActionMap(
            format,
            username,
            flags
        );
    }


    HRESULT STDMETHODCALLTYPE SetActionMap(
        ActionFormat* format,
        const Char* username,
        DWORD flags
    ) override
    {
        return real_->SetActionMap(
            format,
            username,
            flags
        );
    }


    HRESULT STDMETHODCALLTYPE GetImageInfo(
        ImageInfo* info
    ) override
    {
        return real_->GetImageInfo(info);
    }


    HRESULT STDMETHODCALLTYPE EnumEffectsInFile(
        const Char* filename,
        LPDIENUMEFFECTSINFILECALLBACK callback,
        LPVOID user,
        DWORD flags
    ) override
    {
        return real_->EnumEffectsInFile(
            filename,
            callback,
            user,
            flags
        );
    }


    HRESULT STDMETHODCALLTYPE WriteEffectToFile(
        const Char* filename,
        DWORD entries,
        LPDIFILEEFFECT effects,
        DWORD flags
    ) override
    {
        return real_->WriteEffectToFile(
            filename,
            entries,
            effects,
            flags
        );
    }


private:
    static void fill_effect_info(
        EffectInfo& info
    )
    {
        DWORD original_size = info.dwSize;

        ZeroMemory(
            &info,
            sizeof(info)
        );

        info.dwSize =
            original_size
                ? original_size
                : sizeof(info);

        info.guid =
            GUID_ConstantForce;

        info.dwEffType =
            DIEFT_CONSTANTFORCE;

        info.dwStaticParams =
            DIEP_DURATION |
            DIEP_GAIN |
            DIEP_SAMPLEPERIOD |
            DIEP_AXES |
            DIEP_DIRECTION |
            DIEP_TYPESPECIFICPARAMS;

        info.dwDynamicParams =
            DIEP_GAIN |
            DIEP_DIRECTION |
            DIEP_TYPESPECIFICPARAMS;

        if constexpr (Unicode)
        {
            wcscpy_s(
                info.tszName,
                L"G25 Constant Force"
            );
        }
        else
        {
            strcpy_s(
                info.tszName,
                "G25 Constant Force"
            );
        }
    }


    Base* real_ = nullptr;

    volatile LONG ref_count_ = 1;

    DWORD ff_gain_ = DI_FFNOMINALMAX;
    DWORD autocenter_ = DIPROPAUTOCENTER_OFF;
};


// -----------------------------------------------------------------------------
// G25 injection into DIEDFL_FORCEFEEDBACK enumeration
// -----------------------------------------------------------------------------

struct InjectContextA
{
    LPDIENUMDEVICESCALLBACKA callback;
    LPVOID user;
};


struct InjectContextW
{
    LPDIENUMDEVICESCALLBACKW callback;
    LPVOID user;
};


static BOOL CALLBACK inject_g25_a(
    LPCDIDEVICEINSTANCEA instance,
    LPVOID context_ptr
)
{
    if (
        !contains_g25(instance->tszProductName) &&
        !contains_g25(instance->tszInstanceName)
    )
    {
        return DIENUM_CONTINUE;
    }

    auto* context =
        static_cast<InjectContextA*>(
            context_ptr
        );

    DIDEVICEINSTANCEA copy =
        *instance;

    copy.guidFFDriver =
        GUID_G25StandaloneFF;

    log_message(
        "Injecting G25 into FORCEFEEDBACK enumeration"
    );

    return context->callback(
        &copy,
        context->user
    );
}


static BOOL CALLBACK inject_g25_w(
    LPCDIDEVICEINSTANCEW instance,
    LPVOID context_ptr
)
{
    if (
        !contains_g25(instance->tszProductName) &&
        !contains_g25(instance->tszInstanceName)
    )
    {
        return DIENUM_CONTINUE;
    }

    auto* context =
        static_cast<InjectContextW*>(
            context_ptr
        );

    DIDEVICEINSTANCEW copy =
        *instance;

    copy.guidFFDriver =
        GUID_G25StandaloneFF;

    log_message(
        "Injecting G25 into FORCEFEEDBACK enumeration"
    );

    return context->callback(
        &copy,
        context->user
    );
}


// -----------------------------------------------------------------------------
// IDirectInput8 wrapper
// -----------------------------------------------------------------------------

template<bool Unicode>
class DirectInputProxy final
    : public std::conditional_t<
        Unicode,
        IDirectInput8W,
        IDirectInput8A
    >
{
public:
    using Base =
        std::conditional_t<
            Unicode,
            IDirectInput8W,
            IDirectInput8A
        >;

    using Device =
        std::conditional_t<
            Unicode,
            IDirectInputDevice8W,
            IDirectInputDevice8A
        >;

    using Char =
        std::conditional_t<
            Unicode,
            wchar_t,
            char
        >;

    using DeviceInstance =
        std::conditional_t<
            Unicode,
            DIDEVICEINSTANCEW,
            DIDEVICEINSTANCEA
        >;

    using EnumDeviceCallback =
        std::conditional_t<
            Unicode,
            LPDIENUMDEVICESCALLBACKW,
            LPDIENUMDEVICESCALLBACKA
        >;

    using ActionFormat =
        std::conditional_t<
            Unicode,
            DIACTIONFORMATW,
            DIACTIONFORMATA
        >;

    using EnumSemanticCallback =
        std::conditional_t<
            Unicode,
            LPDIENUMDEVICESBYSEMANTICSCBW,
            LPDIENUMDEVICESBYSEMANTICSCBA
        >;

    using ConfigureParams =
        std::conditional_t<
            Unicode,
            DICONFIGUREDEVICESPARAMSW,
            DICONFIGUREDEVICESPARAMSA
        >;


    explicit DirectInputProxy(Base* real)
        : real_(real)
    {
        log_message(
            "DirectInputProxy created (%s)",
            Unicode ? "Unicode" : "ANSI"
        );
    }


    ~DirectInputProxy()
    {
        if (real_)
            real_->Release();

        log_message("DirectInputProxy destroyed");
    }


    HRESULT STDMETHODCALLTYPE QueryInterface(
        REFIID riid,
        void** out
    ) override
    {
        if (!out)
            return E_POINTER;

        bool supported =
            IsEqualGUID(riid, IID_IUnknown);

        if constexpr (Unicode)
            supported |= IsEqualGUID(riid, IID_IDirectInput8W);
        else
            supported |= IsEqualGUID(riid, IID_IDirectInput8A);

        if (supported)
        {
            *out = static_cast<Base*>(this);
            AddRef();
            return S_OK;
        }

        return real_->QueryInterface(
            riid,
            out
        );
    }


    ULONG STDMETHODCALLTYPE AddRef() override
    {
        return InterlockedIncrement(&ref_count_);
    }


    ULONG STDMETHODCALLTYPE Release() override
    {
        ULONG count =
            InterlockedDecrement(&ref_count_);

        if (count == 0)
            delete this;

        return count;
    }


    HRESULT STDMETHODCALLTYPE CreateDevice(
        REFGUID guid,
        Device** out,
        LPUNKNOWN outer
    ) override
    {
        if (!out)
            return E_POINTER;

        Device* real_device = nullptr;

        HRESULT hr =
            real_->CreateDevice(
                guid,
                &real_device,
                outer
            );

        if (
            FAILED(hr) ||
            !real_device
        )
        {
            *out = nullptr;
            return hr;
        }

        DeviceInstance info{};
        info.dwSize = sizeof(info);

        bool is_g25 = false;

        if (
            SUCCEEDED(
                real_device->GetDeviceInfo(&info)
            )
        )
        {
            is_g25 =
                contains_g25(info.tszProductName) ||
                contains_g25(info.tszInstanceName);
        }

        if (!is_g25)
        {
            *out = real_device;
            return hr;
        }

        log_message(
            "CreateDevice: wrapping G25"
        );

        *out =
            new G25DeviceProxy<Unicode>(
                real_device
            );

        return DI_OK;
    }


    HRESULT STDMETHODCALLTYPE EnumDevices(
        DWORD device_type,
        EnumDeviceCallback callback,
        LPVOID user,
        DWORD flags
    ) override
    {
        if (!callback)
            return DIERR_INVALIDPARAM;

        bool wants_ffb =
            (flags & DIEDFL_FORCEFEEDBACK) != 0;

        if (!wants_ffb)
        {
            return real_->EnumDevices(
                device_type,
                callback,
                user,
                flags
            );
        }

        // First pass: preserve any device Windows already considers FFB-capable.
        HRESULT hr =
            real_->EnumDevices(
                device_type,
                callback,
                user,
                flags
            );

        if (FAILED(hr))
            return hr;

        // Second pass: enumerate normally, then inject only the G25.
        DWORD relaxed_flags =
            flags & ~DIEDFL_FORCEFEEDBACK;

        if constexpr (Unicode)
        {
            InjectContextW context{
                callback,
                user
            };

            return real_->EnumDevices(
                device_type,
                inject_g25_w,
                &context,
                relaxed_flags
            );
        }
        else
        {
            InjectContextA context{
                callback,
                user
            };

            return real_->EnumDevices(
                device_type,
                inject_g25_a,
                &context,
                relaxed_flags
            );
        }
    }


    HRESULT STDMETHODCALLTYPE GetDeviceStatus(
        REFGUID guid
    ) override
    {
        return real_->GetDeviceStatus(guid);
    }


    HRESULT STDMETHODCALLTYPE RunControlPanel(
        HWND owner,
        DWORD flags
    ) override
    {
        return real_->RunControlPanel(
            owner,
            flags
        );
    }


    HRESULT STDMETHODCALLTYPE Initialize(
        HINSTANCE instance,
        DWORD version
    ) override
    {
        return real_->Initialize(
            instance,
            version
        );
    }


    HRESULT STDMETHODCALLTYPE FindDevice(
        REFGUID class_guid,
        const Char* name,
        LPGUID result
    ) override
    {
        return real_->FindDevice(
            class_guid,
            name,
            result
        );
    }


    HRESULT STDMETHODCALLTYPE EnumDevicesBySemantics(
        const Char* username,
        ActionFormat* format,
        EnumSemanticCallback callback,
        LPVOID user,
        DWORD flags
    ) override
    {
        return real_->EnumDevicesBySemantics(
            username,
            format,
            callback,
            user,
            flags
        );
    }


    HRESULT STDMETHODCALLTYPE ConfigureDevices(
        LPDICONFIGUREDEVICESCALLBACK callback,
        ConfigureParams* params,
        DWORD flags,
        LPVOID user
    ) override
    {
        return real_->ConfigureDevices(
            callback,
            params,
            flags,
            user
        );
    }


private:
    Base* real_ = nullptr;
    volatile LONG ref_count_ = 1;
};


// -----------------------------------------------------------------------------
// Load the real Windows dinput8.dll
// -----------------------------------------------------------------------------

using DirectInput8CreateFn =
    HRESULT (WINAPI*)(
        HINSTANCE,
        DWORD,
        REFIID,
        LPVOID*,
        LPUNKNOWN
    );


static DirectInput8CreateFn get_real_create()
{
    static HMODULE real_module = nullptr;
    static DirectInput8CreateFn real_create = nullptr;

    if (real_create)
        return real_create;

    wchar_t system_dir[MAX_PATH]{};

    GetSystemDirectoryW(
        system_dir,
        static_cast<UINT>(std::size(system_dir))
    );

    std::wstring path =
        system_dir;

    path += L"\\dinput8.dll";

    real_module =
        LoadLibraryW(
            path.c_str()
        );

    if (!real_module)
    {
        log_message(
            "ERROR: could not load real dinput8.dll"
        );

        return nullptr;
    }

    real_create =
        reinterpret_cast<DirectInput8CreateFn>(
            GetProcAddress(
                real_module,
                "DirectInput8Create"
            )
        );

    if (!real_create)
    {
        log_message(
            "ERROR: real DirectInput8Create not found"
        );
    }

    return real_create;
}


// -----------------------------------------------------------------------------
// Exported DirectInput8Create
// -----------------------------------------------------------------------------

extern "C"
HRESULT WINAPI DirectInput8Create(
    HINSTANCE instance,
    DWORD version,
    REFIID riid,
    LPVOID* out,
    LPUNKNOWN outer
)
{
    if (!out)
        return E_POINTER;

    *out = nullptr;

    auto real_create =
        get_real_create();

    if (!real_create)
        return E_FAIL;

    if (IsEqualGUID(riid, IID_IDirectInput8A))
    {
        IDirectInput8A* real = nullptr;

        HRESULT hr =
            real_create(
                instance,
                version,
                riid,
                reinterpret_cast<LPVOID*>(&real),
                outer
            );

        if (
            FAILED(hr) ||
            !real
        )
        {
            return hr;
        }

        log_message(
            "DirectInput8Create: ANSI"
        );

        *out =
            new DirectInputProxy<false>(
                real
            );

        return DI_OK;
    }

    if (IsEqualGUID(riid, IID_IDirectInput8W))
    {
        IDirectInput8W* real = nullptr;

        HRESULT hr =
            real_create(
                instance,
                version,
                riid,
                reinterpret_cast<LPVOID*>(&real),
                outer
            );

        if (
            FAILED(hr) ||
            !real
        )
        {
            return hr;
        }

        log_message(
            "DirectInput8Create: Unicode"
        );

        *out =
            new DirectInputProxy<true>(
                real
            );

        return DI_OK;
    }

    // Unknown interface request: simply forward.
    return real_create(
        instance,
        version,
        riid,
        out,
        outer
    );
}


// -----------------------------------------------------------------------------
// DLL entry point
// -----------------------------------------------------------------------------

BOOL WINAPI DllMain(
    HINSTANCE instance,
    DWORD reason,
    LPVOID
)
{
    if (reason == DLL_PROCESS_ATTACH)
    {
        g_module = instance;

        DisableThreadLibraryCalls(
            instance
        );
    }

    return TRUE;
}
