UDEV_RULE := 70-elgato-wave3.rules
UDEV_DIR  := /etc/udev/rules.d

.PHONY: run install-udev uninstall-udev

run:
	python3 -m wave3

install-udev:
	install -m 0644 $(UDEV_RULE) $(UDEV_DIR)/$(UDEV_RULE)
	udevadm control --reload-rules
	udevadm trigger --subsystem-match=usb --attr-match=idVendor=0fd9
	@echo "Installed. Replug the Wave:3 if the panel still reports permission denied."

uninstall-udev:
	rm -f $(UDEV_DIR)/$(UDEV_RULE)
	udevadm control --reload-rules

install-mixer:
	python3 -c "from wave3 import mixer; c=mixer.load_channels(); p,u,h=mixer.install(c); mixer.save_channels(c); print('config:',p); print('hardware out:',h); mixer.restart_pipewire(); print('pipewire restarted')"

uninstall-mixer:
	python3 -c "from wave3 import mixer; print('removed' if mixer.uninstall() else 'nothing to remove'); mixer.restart_pipewire()"

test:
	python3 tests/test_ui_race.py
	python3 tests/test_mix_isolation.py
	python3 tests/test_watchdog.py

install-fx:
	python3 -c "from wave3 import fx, mixer; \
	src=mixer.resolve_node(mixer.WAVE3_SOURCE_MATCH,'Audio/Source'); \
	r=fx.apply_state(fx.build_rack(), fx.load_state()); \
	print('fx:', fx.install(r, src)); fx.save_state(fx.rack_to_state(r)); \
	c=mixer.load_channels(); mixer.install(c, fx_source=fx.FX_SOURCE); \
	mixer.restart_pipewire(); print('pipewire restarted')"

uninstall-fx:
	python3 -c "from wave3 import fx, mixer; \
	print('removed' if fx.uninstall() else 'nothing to remove'); \
	c=mixer.load_channels(); mixer.install(c); mixer.restart_pipewire()"
