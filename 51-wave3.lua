-- Elgato Wave:3 (0fd9:0070) - never suspend.
--
-- The capsule suspends when idle and then hands out digital silence instead
-- of resuming, so every mic meter reads a confident -90 dB that means "not
-- measuring" rather than "silent".
--
-- WirePlumber 0.4 reads Lua from main.lua.d. The monitor.alsa.rules block
-- used by 0.5 is silently ignored here, which is worth knowing because a
-- config that does nothing looks exactly like a config that works.
wave3_rule = {
  matches = {
    { { "node.name", "matches", "alsa_input.usb-Elgato_Systems_Elgato_Wave_3*" } },
    { { "node.name", "matches", "alsa_output.usb-Elgato_Systems_Elgato_Wave_3*" } },
  },
  apply_properties = {
    ["session.suspend-timeout-seconds"] = 0,
    ["node.pause-on-idle"] = false,
  },
}

table.insert(alsa_monitor.rules, wave3_rule)
