from __future__ import annotations

import ctypes
import uuid
from ctypes import wintypes


DIRECTINPUT_VERSION = 0x0800

DI8DEVCLASS_GAMECTRL = 4

DIEDFL_ATTACHEDONLY = 0x00000001
DIEDFL_FORCEFEEDBACK = 0x00000100

DIENUM_CONTINUE = 1

MAX_PATH = 260


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def make_guid(value: str) -> GUID:
    u = uuid.UUID(value)

    data4 = bytes([
        u.fields[3],
        u.fields[4],
    ]) + u.fields[5].to_bytes(6, "big")

    return GUID(
        u.fields[0],
        u.fields[1],
        u.fields[2],
        (ctypes.c_ubyte * 8)(*data4),
    )


def guid_to_string(guid: GUID) -> str:
    d4 = bytes(guid.Data4)

    return (
        f"{guid.Data1:08X}-"
        f"{guid.Data2:04X}-"
        f"{guid.Data3:04X}-"
        f"{d4[0]:02X}{d4[1]:02X}-"
        f"{''.join(f'{b:02X}' for b in d4[2:])}"
    )


def guid_is_zero(guid: GUID) -> bool:
    return (
        guid.Data1 == 0
        and guid.Data2 == 0
        and guid.Data3 == 0
        and all(b == 0 for b in guid.Data4)
    )


class DIDEVICEINSTANCEW(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("guidInstance", GUID),
        ("guidProduct", GUID),
        ("dwDevType", wintypes.DWORD),
        ("tszInstanceName", wintypes.WCHAR * MAX_PATH),
        ("tszProductName", wintypes.WCHAR * MAX_PATH),
        ("guidFFDriver", GUID),
        ("wUsagePage", wintypes.WORD),
        ("wUsage", wintypes.WORD),
    ]


HRESULT = ctypes.c_long


ENUM_CALLBACK = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    ctypes.POINTER(DIDEVICEINSTANCEW),
    ctypes.c_void_p,
)


# IID_IDirectInput8W
IID_IDirectInput8W = make_guid(
    "BF798031-483A-4DA2-AA99-5D64ED369700"
)


def enumerate_devices(di_ptr, flags: int):
    results = []

    @ENUM_CALLBACK
    def callback(instance_ptr, context):
        instance = instance_ptr.contents

        results.append({
            "instance": instance.tszInstanceName,
            "product": instance.tszProductName,
            "product_guid": guid_to_string(instance.guidProduct),
            "ff_driver": (
                None
                if guid_is_zero(instance.guidFFDriver)
                else guid_to_string(instance.guidFFDriver)
            ),
        })

        return DIENUM_CONTINUE

    # IDirectInput8W vtable:
    # 0 QueryInterface
    # 1 AddRef
    # 2 Release
    # 3 CreateDevice
    # 4 EnumDevices
    vtable = ctypes.cast(
        di_ptr,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
    ).contents

    enum_devices_type = ctypes.WINFUNCTYPE(
        HRESULT,
        ctypes.c_void_p,
        wintypes.DWORD,
        ENUM_CALLBACK,
        ctypes.c_void_p,
        wintypes.DWORD,
    )

    enum_devices = enum_devices_type(vtable[4])

    hr = enum_devices(
        di_ptr,
        DI8DEVCLASS_GAMECTRL,
        callback,
        None,
        flags,
    )

    if hr < 0:
        raise OSError(
            f"IDirectInput8::EnumDevices failed: "
            f"0x{hr & 0xFFFFFFFF:08X}"
        )

    return results


def release(di_ptr):
    vtable = ctypes.cast(
        di_ptr,
        ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
    ).contents

    release_type = ctypes.WINFUNCTYPE(
        wintypes.ULONG,
        ctypes.c_void_p,
    )

    release_fn = release_type(vtable[2])
    release_fn(di_ptr)


def main():
    dinput8 = ctypes.WinDLL("dinput8.dll")
    kernel32 = ctypes.WinDLL("kernel32.dll")

    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE

    direct_input_create = dinput8.DirectInput8Create

    direct_input_create.argtypes = [
        wintypes.HINSTANCE,
        wintypes.DWORD,
        ctypes.POINTER(GUID),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
    ]

    direct_input_create.restype = HRESULT

    di = ctypes.c_void_p()

    hr = direct_input_create(
        kernel32.GetModuleHandleW(None),
        DIRECTINPUT_VERSION,
        ctypes.byref(IID_IDirectInput8W),
        ctypes.byref(di),
        None,
    )

    if hr < 0:
        raise OSError(
            f"DirectInput8Create failed: "
            f"0x{hr & 0xFFFFFFFF:08X}"
        )

    try:
        all_devices = enumerate_devices(
            di,
            DIEDFL_ATTACHEDONLY,
        )

        ffb_devices = enumerate_devices(
            di,
            DIEDFL_ATTACHEDONLY | DIEDFL_FORCEFEEDBACK,
        )

        print("DirectInput — attached game controllers")
        print("---------------------------------------")

        if not all_devices:
            print("(none)")

        for device in all_devices:
            print()
            print(f"Name:       {device['instance']}")
            print(f"Product:    {device['product']}")
            print(f"FF driver:  {device['ff_driver'] or '(none)'}")

        print()
        print()
        print("DirectInput — force feedback devices")
        print("------------------------------------")

        if not ffb_devices:
            print("(none)")
        else:
            for device in ffb_devices:
                print()
                print(f"Name:       {device['instance']}")
                print(f"Product:    {device['product']}")
                print(f"FF driver:  {device['ff_driver'] or '(none)'}")

        print()
        print("------------------------------------")

        g25_all = [
            d for d in all_devices
            if "g25" in (
                d["instance"] + " " + d["product"]
            ).lower()
        ]

        g25_ffb = [
            d for d in ffb_devices
            if "g25" in (
                d["instance"] + " " + d["product"]
            ).lower()
        ]

        if g25_all and g25_ffb:
            print("RESULT: G25 IS advertised as DirectInput FFB-capable.")
        elif g25_all:
            print("RESULT: G25 is visible to DirectInput,")
            print("        but NOT advertised as FFB-capable.")
        else:
            print("RESULT: G25 was not found by DirectInput.")

    finally:
        release(di)


if __name__ == "__main__":
    main()
