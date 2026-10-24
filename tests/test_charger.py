from dataclasses import replace

from lavalier.charger import ChargerDecision, cdc_present, charger_decision, read_ioreg

IOREG_WITH_PENDANT = '''
  | +-o Pendant@01100000  <class IOUSBHostDevice, id 0x100003a2b, registered, matched, active, busy 0 (12 ms), retain 24>
  |     {
  |       "idProduct" = 272
  |       "USB Product Name" = "Pendant"
  |       "USB Vendor Name" = "ZEPHYR"
  |       "idVendor" = 12259
  |     }
'''


def test_cdc_present_needs_product_and_vendor():
    assert cdc_present(IOREG_WITH_PENDANT)
    assert not cdc_present(IOREG_WITH_PENDANT.replace("ZEPHYR", "Apple"))
    assert not cdc_present("")


def test_charger_signal_order(snap):
    assert charger_decision(snap, cdc=True, quiet_polls=0) == ChargerDecision(True, "usb-cdc")
    assert charger_decision(replace(snap, current_ma=51), cdc=False, quiet_polls=0) == ChargerDecision(True, "current")
    assert charger_decision(snap, cdc=False, quiet_polls=2) == ChargerDecision(True, "quiet-polls")
    assert charger_decision(snap, cdc=False, quiet_polls=1) == ChargerDecision(False, "none")
    assert charger_decision(replace(snap, has_all_fields=False, current_ma=51), cdc=False, quiet_polls=5) == ChargerDecision(False, "none")
    assert charger_decision(None, cdc=False, quiet_polls=5) == ChargerDecision(False, "none")


def test_read_ioreg_never_opens_the_serial_port_and_tolerates_failure():
    seen = []

    def run(cmd, **kw):
        seen.append(cmd)
        raise FileNotFoundError("ioreg")

    assert read_ioreg(run=run) == ""
    assert seen[0][0] == "ioreg" and not any("/dev/" in a for a in seen[0])


NESTED_IOREG = '''
  | +-o Hub@01000000  <class IOUSBHostDevice>
  | | {
  | |   "USB Vendor Name" = "ZEPHYR"
  | | }
  | +-o Pendant@01100000  <class IOUSBHostDevice>
  | | {
  | |   "USB Product Name" = "Pendant"
  | |   "USB Vendor Name" = "ZEPHYR"
  | | }
'''


def test_cdc_present_handles_nested_pipe_prefixes_and_keeps_strings_in_one_block():
    assert cdc_present(NESTED_IOREG)
    split = NESTED_IOREG.replace('  | |   "USB Vendor Name" = "ZEPHYR"\n  | | }\n  | +-o Pendant',
                                 '  | | }\n  | +-o Pendant')
    assert split.count('"USB Vendor Name" = "ZEPHYR"') == 1
    assert not cdc_present(split.replace('  | | {\n  | |   "USB Product Name" = "Pendant"\n  | |   "USB Vendor Name" = "ZEPHYR"\n',
                                         '  | | {\n  | |   "USB Product Name" = "Pendant"\n'))
