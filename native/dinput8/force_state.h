#pragma once

#include <algorithm>
#include <cstdint>
#include <map>

// Pure force arithmetic/state: no Windows or HID dependencies, so it can be
// tested without attaching a wheel. All methods are called under the proxy's
// output mutex.
class ForceState
{
public:
    struct Effect
    {
        int32_t magnitude = 0;
        uint32_t gain = 10000;
        int direction = 1;
        bool playing = false;
    };

    uint64_t add()
    {
        const uint64_t id = next_id_++;
        effects_.emplace(id, Effect{});
        return id;
    }

    void remove(uint64_t id)
    {
        effects_.erase(id);
    }

    void update(uint64_t id, const Effect& effect)
    {
        auto it = effects_.find(id);
        if (it != effects_.end())
            it->second = effect;
    }

    void set_parameters(uint64_t id, int32_t magnitude, uint32_t gain, int direction)
    {
        auto it = effects_.find(id);
        if (it != effects_.end())
        {
            it->second.magnitude = magnitude;
            it->second.gain = gain;
            it->second.direction = direction;
        }
    }

    void set_playing(uint64_t id, bool playing)
    {
        auto it = effects_.find(id);
        if (it != effects_.end())
            it->second.playing = playing;
    }

    bool is_playing(uint64_t id) const
    {
        const auto it = effects_.find(id);
        return it != effects_.end() && it->second.playing;
    }

    bool paused() const { return paused_; }
    bool actuators_enabled() const { return actuators_; }
    bool any_playing() const
    {
        for (const auto& entry : effects_)
            if (entry.second.playing)
                return true;
        return false;
    }

    void set_device_gain(uint32_t gain)
    {
        device_gain_ = std::min<uint32_t>(gain, 10000);
    }

    uint32_t device_gain() const
    {
        return device_gain_;
    }

    void stop_all()
    {
        for (auto& entry : effects_)
            entry.second.playing = false;
    }

    void pause() { paused_ = true; }
    void resume() { paused_ = false; }
    void set_actuators(bool enabled) { actuators_ = enabled; }

    int32_t force() const
    {
        if (paused_ || !actuators_)
            return 0;

        int64_t sum = 0;

        for (const auto& entry : effects_)
        {
            const Effect& effect = entry.second;
            if (!effect.playing)
                continue;

            // Scale the signed force before summing. Keep intermediate values
            // wide enough for many active effects; clamp only at the output.
            const int64_t magnitude =
                std::clamp<int64_t>(effect.magnitude, -10000, 10000);
            const int64_t gain = std::min<uint32_t>(effect.gain, 10000);
            sum += magnitude * gain / 10000 * effect.direction;
        }

        sum = sum * device_gain_ / 10000;
        return static_cast<int32_t>(std::clamp<int64_t>(sum, -10000, 10000));
    }

private:
    std::map<uint64_t, Effect> effects_;
    uint64_t next_id_ = 1;
    uint32_t device_gain_ = 10000;
    bool paused_ = false;
    bool actuators_ = true;
};
