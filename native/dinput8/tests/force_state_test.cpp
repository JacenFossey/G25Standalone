#include "../force_state.h"

#include <cassert>

int main()
{
    ForceState state;
    const auto first = state.add();
    const auto second = state.add();
    ForceState::Effect a{8000, 10000, 1, true};
    ForceState::Effect b{-3000, 10000, 1, true};

    state.update(first, a);
    assert(state.force() == 8000);
    state.update(second, b);
    assert(state.force() == 5000); // simultaneous opposing forces

    a.gain = 5000;
    state.update(first, a);
    assert(state.force() == 1000);
    state.set_device_gain(5000);
    assert(state.force() == 500); // independent effect and device gain
    state.stop_all();
    state.set_parameters(first, 8000, 5000, 1);
    assert(!state.is_playing(first)); // parameter updates do not restart STOPALL
    state.set_playing(first, true);
    state.set_playing(second, true);

    a.direction = -1;
    state.update(first, a);
    assert(state.force() == -3500);
    state.set_device_gain(10000);
    a.gain = 10000;
    state.update(first, a);
    assert(state.force() == -10000); // sum saturates safely

    state.remove(first);
    assert(state.force() == -3000); // other effect survives destruction
    state.pause();
    assert(state.force() == 0);
    assert(state.paused());
    state.resume();
    assert(state.force() == -3000);
    state.set_actuators(false);
    assert(state.force() == 0);
    state.set_actuators(true);
    state.stop_all();
    assert(state.force() == 0);

    b.playing = true;
    state.update(second, b);
    state.set_device_gain(0);
    assert(state.force() == 0);
    state.set_device_gain(10000);
    assert(state.force() == -3000);
    state.remove(second);
    assert(state.force() == 0);
}
