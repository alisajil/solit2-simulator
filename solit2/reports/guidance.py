"""What the SOLIT² Engineering Guidance requires of a full-scale fire test.

Pure data with citations, kept apart from the document that reads it so a
reviewer can check the numbers against the standard without reading prose,
and so changing a requirement is a change to one cited line.

Three sources, and they do not say the same thing:

- **Annex 7** (v2.1) is the detailed test protocol: design fires, mock-up,
  instrumentation, acceptance categories, reporting.
- **The main document §3.6.2** carries its own, partly different, list of test
  requirements -- a taller minimum tunnel, a sampling rate, a number of test
  series, and a measurement schedule that is not Annex 7's Table 5.
- **Annex 3 §3.3** lists the design parameters that shall be *derived* from
  full-scale testing, which is what fixes the envelope a later tunnel has to
  sit inside.

Where two of them set a minimum for the same thing, both bind, and the test
has to satisfy the stricter. `STRICTER_OF` records those pairs rather than
silently picking one.
"""
from __future__ import annotations

# ---------------------------------------------------------------- Annex 7 §3-§5
MIN_TEST_TUNNEL = {"free area (m2)": 40.0, "height (m)": 4.5, "length (m)": 400.0}  # §3.6
CLASS_A_MIN_UNSUPPRESSED_MW = 150.0        # §5.2.1
CLASS_A_MIN_PALLETS = 400                  # §5.2.2, "approximately 110-140 GJ"
CLASS_A_ENERGY_GJ = (110.0, 140.0)         # §5.2.2
MOCKUP_MIN_M = {"height": 4.0, "fuel height": 2.5, "width": 2.4, "length": 10.0}   # §5.2.2
PALLET_MM = (800, 1200, 144)               # §5.2.4, length x width x height
PALLET_MASS_KG = (22.0, 25.0)              # §5.2.4
MAX_PALLET_MOISTURE_PCT = 18.0             # §5.2.4
MAX_WALL_CLEARANCE_M = 1.5                 # §5.2.3, eccentric placement
FRAME_COVERAGE_MAX_PCT = 10.0              # §5.2.2, steel frames vs fuel faces
IGNITION_PAN_MM = (600, 150, 50)           # §5.2.5
IGNITION_PANS = 2                          # §5.2.5, "at least"
IGNITION_PETROL_L = 2.0                    # §5.2.5, per pan
TARGET_STANDOFF_M = 5.0                    # §5.2.6, target at D10
TEST_VELOCITIES_MS = (1.5, 3.0)            # §5.2.7 and §5.3.6
VELOCITY_STATION_M = {"A": 45.0, "B": 20.0}  # §5.2.7 upstream; §5.3.6 upstream
ACTIVATION_MIN_AFTER_IGNITION_S = 60.0     # §5.2.8 option A
MIN_DISCHARGE_MIN = 30.0                   # §5.2.8
ACTIVATION_AREA_MIN_MULTIPLE = 3.0         # §5.2.8, of mock-up length
CLASS_B_MIN_MW = 50.0                      # §5.3.1
CLASS_B_POOL_MIN_M = {"width": 2.5, "length": 6.5, "height above road": 0.5}      # §5.3.2
CLASS_B_SINGLE_POOL_MIN_M2 = 4.0           # §5.3.2
CLASS_B_MIN_BURN_MIN = 7.0                 # §5.3.4, unsuppressed
CLASS_B_IGNITION_WITHIN_S = 60.0           # §5.3.5
CLASS_B_TRIGGER_WITHIN_S = 120.0           # §5.3.7
NOZZLE_SPREAD_MAX_PCT = 10.0               # §4, last nozzle to first
FLOW_TOLERANCE_PCT = 5.0                   # §6.4.7
HRR_MAX_DELAY_S = 60.0                     # §6.5
CALIBRATION_POOL_MW = (5.0, 30.0)          # §6.2

# ------------------------------------------------- main document §3.6.2, p.58-59
# Its own test requirements, which Annex 7 does not repeat. Read together, not
# instead of: a protocol built only from Annex 7 misses the sampling rate, the
# number of test series and the standoff tolerance entirely.
MAIN_MIN_TEST_TUNNEL = {"length (m)": 400.0, "height (m)": 5.0, "width (m)": 7.0}
MAIN_MIN_TEST_SERIES = 3                   # "At least 3 series of tests"
MAIN_MAX_SAMPLE_INTERVAL_S = 2.0           # "measured and collated at least every 2 s"
MAIN_MAX_STANDOFF_EXCESS_PCT = 20.0        # real nozzle-to-load distance vs tested
MAIN_SPRAY_DEVIATION_MS = (1.0, 3.0, 5.0)  # "must be defined at least at"
MAIN_TYPICAL_LONGITUDINAL_MS = (2.0, 3.0)  # "normally used", not a requirement
MAIN_MEASUREMENT_SCHEDULE = [
    ("Temperature, near and above the fire load", "10 separate positions"),
    ("Temperature, along the tunnel",
     "10 m, 20 m, 40 m, 100 m each way from the load centre, 5 points per cross-section"),
    ("Radiant heat", "5 m and 10 m, and within the fire area"),
    ("Flow velocity", "full cross-section, at least 20 m before and after the load"),
    ("Heat release rate", "oxygen consumption method"),
    ("System pressure and flow rate", "recorded throughout"),
    ("Gas concentrations", "3 positions, 40 m from the fire"),
    ("Imaging", "photographic, video and infrared, for every test"),
]

# Where both documents set a floor for the same property, the test must clear
# the higher one. Annex 7 §3.6 lets the authority accept different values; the
# main document does not say so, which is a reason to raise it with them
# explicitly rather than assume the weaker figure governs.
STRICTER_OF = [
    ("Test tunnel length", 400.0, 400.0, "m", "§3.6 / §3.6.2"),
    ("Test tunnel height", 4.5, 5.0, "m", "§3.6 / §3.6.2"),
]

# ------------------------------------------------------------- Annex 3 §3.3, p.10
# "All major design parameters of any FFFS shall be derived from full scale
# fire testing", and this is the list. It matters twice over: it is what the
# test has to pin down, and it is the envelope §3.3 then confines a protected
# tunnel to.
TEST_DERIVED_PARAMETERS = [
    "Nozzle types and K-factors",
    "Minimum and maximum working pressure",
    "Nozzle positions",
    "Nozzle spacing, longitudinal and transversal",
    "Minimum and maximum installation height",
    "Minimum and maximum ventilation conditions",
    "Maximum fire size at activation",
    "Time to full operation",
    "Minimum and maximum section lengths",
    "Minimum and maximum number of sections activated simultaneously",
]

# ------------------------------------------------------------------ Annex 7 §6.4
# Range and accuracy are the standard's floor, not a recommendation: "shall be
# able to measure", "minimum accuracy".
INSTRUMENT_SPEC = [
    ("Thermocouple", "TC", "type K, 1.0 mm", "up to 1300 °C", "±1 %", "§6.4.1"),
    ("Heat flux", "HF", "Gordon (Medtherm)", "up to 20 W/cm²", "±3 %", "§6.4.2"),
    ("Oxygen", "GA", "electrochemical", "0–25 vol %", "±0.5 %", "§6.4.3"),
    ("Carbon dioxide", "GA", "—", "0–25 vol %", "±10 %", "§6.4.3"),
    ("Carbon monoxide", "GA", "—", "0–10 vol %", "±5 %", "§6.4.3"),
    ("Air velocity", "AN", "ultrasonic or bidirectional probe",
     "−15 to +15 m/s", "±1 %", "§6.4.4"),
    ("Visibility", "VI", "opacimeter, or LED lines on video", "1/m", "1 %", "§6.4.5"),
    ("System pressure", "—", "transducer at the hydraulically last nozzle",
     "—", "±1 % absolute", "§6.4.6"),
    ("Flow rate", "—", "sensor between pump unit and activated sections",
     "—", "±1 %", "§6.4.7"),
]

# Annex 7 §5.4 Table 4. The optional pair is the standard's own wording, not a
# softening of it: an uncovered mock-up lets water reach the seat of the fire
# immediately, which §5.2.2 calls unrealistic for most real HGVs.
MINIMUM_TESTS = [
    ("1", "Class A — HGV", "with tarpaulin cover", "1.5 m/s", "required"),
    ("2", "Class A — HGV", "with tarpaulin cover", "3.0 m/s", "required"),
    ("3", "Class B — min. 50 MW", "pool", "1.5 m/s", "required"),
    ("4", "Class B — min. 50 MW", "pool", "3.0 m/s", "required"),
    ("—", "Class A — HGV", "without tarpaulin cover", "1.5 m/s", "optional"),
    ("—", "Class A — HGV", "without tarpaulin cover", "3.0 m/s", "optional"),
]

# ------------------------------------------------------------------- Annex 4, DE
# The worked quantitative risk analysis. Annex 7 §3.1 makes the risk analysis
# the thing that chooses the design fire and the scenarios, so its assumptions
# are the ones a test has to stay consistent with. These are that example's
# figures -- a worked illustration on a model tunnel, NOT limits for any other
# tunnel, and reproduced here only so the protocol can point at the method.
RISK_ANALYSIS_EXAMPLE = {
    "model tunnel": "1200 m, directional traffic, 2 lanes, 9.50 × 5.00 m clear, 3 % gradient",
    "traffic": "60 000 vehicles/day, 18 % heavy goods, daily congestion assumed",
    "design fires (RABT 2006)": "car 5 MW, bus or HGV 30 MW, 100 MW where heavy "
                                "goods traffic exceeds 6000 HGV-km per day per bore",
    "fire location": "tunnel mid-point",
    "detection": "successful within 60 s, or not at all",
    "activation": "ignition at t=60 s, detection at t=120 s, ventilation and the "
                  "system both start at t=180 s, i.e. 120 s after ignition",
    "escape model": "5 m visibility at 1.50 m height, walking 1.3 m/s, starting 60 s "
                    "after ignition; half the people in a marginal zone get out",
    "traffic states": "free flow, and standing congestion on both sides of the fire",
}
# Annex 4 §5.2: the worked comparison came out at 30.04e-3 against 30.71e-3
# expected damage, and the text's own reading of that gap is the useful part.
RISK_RANKING_NOISE_PCT = 2.0


# Annex 7 §8.2: what a fire test protocol "shall cover as a minimum", verbatim
# in substance. The protocol document is checked against this list, because a
# protocol missing one of these is not one the authority can approve.
PROTOCOL_CONTENTS = [
    "Description of referred to test standards and variations if any",
    "Description of the test tunnel",
    "Description of test setup (instruments, methodology, measurement grids)",
    "Description of system calibration",
    "Description of fire load and target in all tests",
    "Description of fire ignition",
    "Activation times",
    "Geometry of the test tunnel",
    "Ventilation conditions",
    "Categorization of the intended FFFS",
    "Intended system parameters",
    "Fire test program schedule",
]

# Each §8.2 item, and a phrase that must appear in the rendered protocol for it
# to be covered. Keeping the mapping here rather than in the test means the
# document and the checklist move together.
CONTENT_MARKERS = {
    "test standards and variations": "Standards referred to, and variations",
    "test tunnel": "Test tunnel — description and geometry",
    "test setup": "instruments, methodology and measurement grid",
    "system calibration": "System calibration",
    "fire load and target": "Fire load and target",
    "fire ignition": "Ignition (§5.2.5)",
    "activation times": "Activation times (§5.2.8)",
    "tunnel geometry": "Free cross-section",
    "ventilation conditions": "Ventilation conditions (§5.2.7)",
    "FFFS categorisation": "FFFS categorisation",
    "system parameters": "Nozzle K-factor",
    "test programme schedule": "Fire test programme",
}
