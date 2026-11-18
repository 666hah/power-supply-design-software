"""Load-current injection and control-path consistency for the loop models."""
import json
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from design_engine.specification import load_spec
from nonisolated import Kernel
from plants import (
    ActiveClampForwardConverter, BoostConverter, BuckBoostConverter, BuckConverter,
    FlybackConverter, _legacy_load_plant, build_loop_models,
)
from power_stage import compute_operating_point


def example(name):
    return load_spec(json.loads((ROOT/'examples'/name).read_text(encoding='utf-8')))


class LoadStepPlantCheck(unittest.TestCase):
    def test_nominal_command_path_keeps_the_existing_bode_model(self):
        shared = (48, 250e3, 40e-6, 220e-6, 2)
        plants = (
            BuckConverter(24, 12, *shared),
            BoostConverter(12, 24, *shared),
            BuckBoostConverter(24, 12, *shared),
            FlybackConverter(24, 12, *shared, N=1.25, Vf=0),
            ActiveClampForwardConverter(30, 12, *shared, N=1.25, Vf=0),
        )
        s = 2j*np.pi*np.geomspace(2, 100e3, 30)
        eta = 0.93
        for plant in plants:
            for mode in ('CCM', 'DCM'):
                plant.mode = mode
                plant.D_actual = plant.D*0.8
                for peak in (False, True):
                    with self.subTest(plant=type(plant).__name__, mode=mode, peak=peak):
                        command = (plant.get_peak_current_mode_transfer_function() if peak else
                                   plant.get_voltage_mode_transfer_function())
                        signed_gain = np.sign(command(0).real)
                        model, _ = _legacy_load_plant(plant, peak, eta)
                        np.testing.assert_allclose(model[0, 0](s), eta*signed_gain*command(s),
                                                   rtol=2e-12, atol=1e-12)
                        self.assertLessEqual(model[0, 1](0).real, 0.)
                        if mode == 'DCM':
                            high = s[-1]
                            np.testing.assert_allclose(model[0, 1](high)*high*plant.C_out/eta,
                                                       -1, rtol=0.03)

    def test_qr_load_channel_follows_the_parallel_bank_admittance(self):
        for filename in ('90W_QR_L6565_300V_TUNED.json', '90W_QR_L6565_252_442V_REFERENCE.json'):
            with self.subTest(filename=filename):
                params = example(filename)
                params = dict(params, coupling_config=dict(enabled=False))
                op = compute_operating_point(params)
                (command, _, _), details = build_loop_models(params, op)
                source = command._load_plant
                point = details.qr_linearization
                s = 2j*np.pi*np.geomspace(4, 20e3, 50)
                admittance = sum(s*c/(1+s*c*r) for c, r in point['capacitors'])
                expected = -1/(point['output_conductance']+admittance)
                # The Bode transfer applies polynomial minreal cancellation.
                np.testing.assert_allclose(source[0, 0](s), command(s), rtol=5e-8)
                np.testing.assert_allclose(source[0, 1](s), expected, rtol=1e-12)

    def test_period_load_sensitivity_matches_a_dc_sink_in_each_phase(self):
        for filename in ('24W_BUCK_VM_TPS40200.json', '24W_BUCK_PCM_LTC3864.json',
                         '24W_BOOST_PCM_LM5022.json'):
            with self.subTest(filename=filename):
                params = example(filename)
                op = compute_operating_point(params)
                model = op['niso_model']
                kernel = Kernel(model['parameters'], model['dcr'])
                initial = np.asarray(model['initial'])
                duty = model['D']
                db, df, peak = kernel.load_derivative_ccm(duty)

                def period_with_extra_sink(sink):
                    # In the load-resistor equation, reducing the DC voltage
                    # offset by R*I is equivalent to placing an ideal sink I
                    # in parallel. Measure capacitor voltage without the offset.
                    perturbed = Kernel(model['parameters'], model['dcr'])
                    perturbed.block -= sink*perturbed.R
                    perturbed.phases = [perturbed.matrix(state) for state in (True, False, None)]
                    ending, mean, _ = perturbed.period(initial, duty, False)
                    on_current = perturbed.flow(initial, 0, duty*perturbed.T)[0][0]
                    return np.r_[ending, mean, on_current]

                h = 1e-3
                expected = (period_with_extra_sink(h)-period_with_extra_sink(-h))/(2*h)
                np.testing.assert_allclose(np.r_[db.ravel(), df.ravel(), peak], expected, atol=1e-9)
                (command, _, _), _ = build_loop_models(params, op)
                s = 2j*np.pi*np.geomspace(5, 20e3, 30)
                np.testing.assert_allclose(command._load_plant[0, 0](s), command(s), rtol=1e-12)
                self.assertLessEqual(command._load_plant[0, 1](0).real, 0.)


if __name__ == '__main__':
    unittest.main(verbosity=2)
