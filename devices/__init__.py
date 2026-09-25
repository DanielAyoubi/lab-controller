from devices.brooks_mfc import BrooksMFC
from devices.dewmaster import DewMaster
from devices.firesting_o2 import FireStingO2
from devices.julabo_chiller import JulaboChiller
from devices.vaisala_rh import VaisalaRH
from devices.vogtlin_mfc import VogtlinMFC

# The device catalog: every device type the app knows.
# The scan tries them in this order, so keep the quick-to-probe ones first.
DEVICE_TYPES = {
    "vogtlin_mfc": VogtlinMFC,
    "vaisala_rh": VaisalaRH,
    "brooks_mfc": BrooksMFC,
    "julabo_chiller": JulaboChiller,
    "firesting_o2": FireStingO2,
    "dewmaster": DewMaster,
}
