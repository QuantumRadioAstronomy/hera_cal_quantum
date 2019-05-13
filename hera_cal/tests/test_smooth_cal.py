# -*- coding: utf-8 -*-
# Copyright 2018 the HERA Project
# Licensed under the MIT License

from __future__ import absolute_import, division, print_function

import unittest
import numpy as np
from copy import deepcopy
import os
import glob
import sys
import shutil
from scipy import constants
import warnings
from pyuvdata.utils import check_histories
from pyuvdata import UVCal, UVData

from hera_cal import io
from hera_cal import smooth_cal
from hera_cal.datacontainer import DataContainer
from hera_cal.data import DATA_PATH


class Test_Smooth_Cal_Helper_Functions(unittest.TestCase):

    def setUp(self):
        np.random.seed(21)

    def test_time_kernel(self):
        kernel = smooth_cal.time_kernel(100, 10.0, filter_scale=1.0)
        self.assertAlmostEqual(np.sum(kernel), 1.0)
        self.assertEqual(np.max(kernel), kernel[100])
        self.assertEqual(len(kernel), 201)

    def test_smooth_cal_argparser(self):
        sys.argv = [sys.argv[0], 'a', 'b', '--flag_file_list', 'c']
        a = smooth_cal.smooth_cal_argparser()
        self.assertEqual(a.calfits_list, ['a', 'b'])
        self.assertEqual(a.flag_file_list, ['c'])

    def test_time_filter(self):
        gains = np.ones((10, 10), dtype=complex)
        gains[3, 5] = 10.0
        wgts = np.ones((10, 10), dtype=float)
        wgts[3, 5] = 0
        times = np.linspace(0, 10 * 10 / 60. / 60. / 24., 10, endpoint=False)
        tf = smooth_cal.time_filter(gains, wgts, times, filter_scale=1800.0, nMirrors=1)
        np.testing.assert_array_almost_equal(tf, np.ones((10, 10), dtype=complex))

    def test_freq_filter(self):
        gains = np.ones((10, 10), dtype=complex)
        gains[3, 5] = 10.0
        wgts = np.ones((10, 10), dtype=float)
        wgts[3, 5] = 0
        freqs = np.linspace(100., 200., 10, endpoint=False) * 1e6
        ff, info = smooth_cal.freq_filter(gains, wgts, freqs)
        np.testing.assert_array_almost_equal(ff, np.ones((10, 10), dtype=complex))

        # test rephasing
        gains = np.ones((2, 1000), dtype=complex)
        wgts = np.ones((2, 1000), dtype=float)
        freqs = np.linspace(100., 200., 1000, endpoint=False) * 1e6
        gains *= np.exp(2.0j * np.pi * np.outer(150e-9 * np.ones(2), freqs))
        ff, info = smooth_cal.freq_filter(gains, wgts, freqs)
        np.testing.assert_array_almost_equal(ff, gains)

        # test skip_wgt
        gains = np.random.randn(10, 10) + 1.0j * np.random.randn(10, 10)
        wgts = np.ones((10, 10), dtype=float)
        wgts[0, 0:8] = 0
        freqs = np.linspace(100., 200., 10, endpoint=False) * 1e6
        ff, info = smooth_cal.freq_filter(gains, wgts, freqs, skip_wgt=.5)
        np.testing.assert_array_equal(ff[0, :], gains[0, :])
        self.assertTrue(info[0]['skipped'])

    def test_time_freq_2D_filter(self):
        gains = np.ones((100, 100), dtype=complex)
        gains[3, 5] = 10.0
        wgts = np.ones((100, 100), dtype=float)
        wgts[3, 5] = 0
        freqs = np.linspace(100., 200., 100, endpoint=False) * 1e6
        times = np.linspace(0, 10 * 10 / 60. / 60. / 24., 100, endpoint=False)
        ff, info = smooth_cal.time_freq_2D_filter(gains, wgts, freqs, times, filter_mode='rect')
        np.testing.assert_array_almost_equal(ff, np.ones((100, 100), dtype=complex))
        ff, info = smooth_cal.time_freq_2D_filter(gains, wgts, freqs, times, filter_mode='plus')
        np.testing.assert_array_almost_equal(ff, np.ones((100, 100), dtype=complex))

        # test rephasing
        gains = np.ones((100, 100), dtype=complex)
        wgts = np.ones((100, 100), dtype=float)
        gains *= np.exp(2.0j * np.pi * np.outer(-151e-9 * np.ones(100), freqs))
        ff, info = smooth_cal.time_freq_2D_filter(gains, wgts, freqs, times)
        np.testing.assert_array_almost_equal(ff, gains, 4)

        # test errors
        with self.assertRaises(ValueError):
            ff, info = smooth_cal.time_freq_2D_filter(gains, wgts, freqs, times, filter_mode='blah')

    def flag_threshold_and_broadcast(self):
        flags = {(i, 'Jxx'): np.zeros((10, 10), dtype=bool) for i in range(3)}
        for ant in flags.keys():
            flags[ant][4, 0:6] = True
            flags[ant][0:4, 4] = True
        flag_threshold_and_broadcast(flags, freq_threshold=0.35, time_threshold=0.5, ant_threshold=1.0)
        for ant in flags.keys():
            self.assertTrue(np.all(flags[ant][4, :]))
            self.assertTrue(np.all(flags[ant][:, 4]))

        self.assertFalse(np.all(flags[(0, 'Jxx')]))
        flags[(0, 'Jxx')][0:8, :] = True
        flag_threshold_and_broadcast(flags, freq_threshold=1.0, time_threshold=1.0, ant_threshold=0.5)
        self.assertTrue(np.all(flags[0, 'Jxx']))
        self.assertFalse(np.all(flags[1, 'Jxx']))

    def test_pick_reference_antenna(self):
        gains = {(n, 'Jxx'): np.ones((10, 10), dtype=complex) for n in range(10)}
        flags = {(n, 'Jxx'): np.zeros((10, 10), dtype=bool) for n in range(10)}
        freqs = np.linspace(100e6, 200e6, 10)
        for n in range(0, 7):  # add flags to disqualify antennas 0, 1, 2, 3, 4, 5, 6
            flags[(n, 'Jxx')][:, 4] = True
        for n in range(6, 9):  # add phase noise to disqualify antennas 6, 7, 8
            gains[(n, 'Jxx')] *= np.exp(.1j * np.pi * np.random.rand(10, 10))  # want this to be << 2pi to avoid phase wraps
        self.assertEqual(smooth_cal.pick_reference_antenna(gains, flags, freqs, per_pol=False), (9, 'Jxx'))
        self.assertEqual(smooth_cal.pick_reference_antenna(gains, flags, freqs), {'Jxx': (9, 'Jxx')})

    def test_rephase_to_refant(self):
        gains = {(0, 'Jxx'): np.array([1. + 1.0j, 1. - 1.0j]),
                 (1, 'Jxx'): np.array([-1. + 1.0j, -1. - 1.0j])}
        smooth_cal.rephase_to_refant(gains, (0, 'Jxx'))
        np.testing.assert_almost_equal(np.imag(gains[(0, 'Jxx')]), np.zeros_like(np.imag(gains[(0, 'Jxx')])))
        flags = {(0, 'Jxx'): np.array([False, True]),
                 (1, 'Jxx'): np.array([True, False])}
        with self.assertRaises(ValueError):
            smooth_cal.rephase_to_refant(gains, (0, 'Jxx'), flags=flags)


class Test_Calibration_Smoother(unittest.TestCase):

    def setUp(self):
        calfits_list = sorted(glob.glob(os.path.join(DATA_PATH, 'test_input/*.abs.calfits_54x_only')))[0::2]
        flag_file_list = sorted(glob.glob(os.path.join(DATA_PATH, 'test_input/*.uvOCR_53x_54x_only.flags.applied.npz')))[0::2]
        self.cs = smooth_cal.CalibrationSmoother(calfits_list, flag_file_list=flag_file_list, flag_filetype='npz')

    def test_ref_ant(self):
        calfits_list = sorted(glob.glob(os.path.join(DATA_PATH, 'test_input/*.abs.calfits_54x_only')))[0::2]
        flag_file_list = sorted(glob.glob(os.path.join(DATA_PATH, 'test_input/*.uvOCR_53x_54x_only.flags.applied.npz')))[0::2]
        cs = smooth_cal.CalibrationSmoother(calfits_list, flag_file_list=flag_file_list, flag_filetype='npz', pick_refant=True)
        self.assertEqual(cs.refant['Jxx'], (54, 'Jxx'))
        cs.time_freq_2D_filter(window='tukey', alpha=.45)
        cs.rephase_to_refant()
        np.testing.assert_array_almost_equal(np.imag(cs.gain_grids[54, 'Jxx']),
                                             np.zeros_like(np.imag(cs.gain_grids[54, 'Jxx'])))

    def test_check_consistency(self):
        temp_time = self.cs.cal_times[self.cs.cals[0]][0]
        self.cs.cal_times[self.cs.cals[0]][0] = self.cs.cal_times[self.cs.cals[0]][1]
        self.cs.time_indices = {cal: np.searchsorted(self.cs.time_grid, times) for cal, times in self.cs.cal_times.items()}
        with self.assertRaises(AssertionError):
            self.cs.check_consistency()
        self.cs.cal_times[self.cs.cals[0]][0] = temp_time
        self.cs.time_indices = {cal: np.searchsorted(self.cs.time_grid, times) for cal, times in self.cs.cal_times.items()}

        self.cs.cal_freqs[self.cs.cals[0]] += 1
        with self.assertRaises(AssertionError):
            self.cs.check_consistency()
        self.cs.cal_freqs[self.cs.cals[0]] -= 1

        self.cs.flag_freqs[self.cs.flag_files[0]] += 1
        with self.assertRaises(AssertionError):
            self.cs.check_consistency()
        self.cs.flag_freqs[self.cs.flag_files[0]] -= 1

        temp_time = self.cs.flag_times[self.cs.flag_files[0]][0]
        self.cs.flag_times[self.cs.flag_files[0]][0] = self.cs.flag_times[self.cs.flag_files[0]][1]
        self.cs.flag_time_indices = {ff: np.searchsorted(self.cs.time_grid, times) for ff, times in self.cs.flag_times.items()}
        with self.assertRaises(AssertionError):
            self.cs.check_consistency()
        self.cs.flag_times[self.cs.flag_files[0]][0] = temp_time
        self.cs.flag_time_indices = {ff: np.searchsorted(self.cs.time_grid, times) for ff, times in self.cs.flag_times.items()}

    def test_load_cal_and_flags(self):
        self.assertEqual(len(self.cs.freqs), 1024)
        self.assertEqual(len(self.cs.time_grid), 180)
        self.assertAlmostEqual(self.cs.dt, 10.737419128417969 / 24 / 60 / 60)
        self.assertTrue((54, 'Jxx') in self.cs.gain_grids)
        self.assertTrue((54, 'Jxx') in self.cs.flag_grids)
        self.assertEqual(self.cs.gain_grids[54, 'Jxx'].shape, (180, 1024))
        self.assertEqual(self.cs.flag_grids[54, 'Jxx'].shape, (180, 1024))
        np.testing.assert_array_equal(self.cs.flag_grids[54, 'Jxx'][60:120, :], True)

    def test_1D_filtering(self):
        g = deepcopy(self.cs.gain_grids[54, 'Jxx'])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.cs.freq_filter(window='tukey', alpha=.45)
        g2 = deepcopy(self.cs.gain_grids[54, 'Jxx'])
        self.assertFalse(np.all(g == g2))
        self.assertEqual(g2.shape, g.shape)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.cs.time_filter()
        g3 = deepcopy(self.cs.gain_grids[54, 'Jxx'])
        self.assertFalse(np.all(g == g3))
        self.assertEqual(g3.shape, g.shape)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.cs.time_filter()
        g4 = deepcopy(self.cs.gain_grids[54, 'Jxx'])
        self.assertFalse(np.all(g3 == g4))
        self.assertEqual(g4.shape, g.shape)

        self.setUp()
        self.assertFalse(np.all(self.cs.flag_grids[(54, 'Jxx')] == np.ones_like(self.cs.flag_grids[(54, 'Jxx')])))
        self.cs.flag_grids[(54, 'Jxx')] = np.zeros_like(self.cs.flag_grids[(54, 'Jxx')])
        self.cs.flag_grids[(54, 'Jxx')][:, 0:1000] = True
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.cs.freq_filter()
            np.testing.assert_array_equal(self.cs.gain_grids[(54, 'Jxx')], g)
            self.cs.time_filter()
            np.testing.assert_array_equal(self.cs.gain_grids[(54, 'Jxx')], g)
            # test skip_wgt propagation to flags
            np.testing.assert_array_equal(self.cs.flag_grids[(54, 'Jxx')],
                                          np.ones_like(self.cs.flag_grids[(54, 'Jxx')]))
        self.setUp()
        self.cs.gain_grids[54, 'Jxx'] = g

    def test_2D_filtering(self):
        g = deepcopy(self.cs.gain_grids[54, 'Jxx'])
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.cs.time_freq_2D_filter(window='tukey', alpha=.45)
        g2 = deepcopy(self.cs.gain_grids[54, 'Jxx'])
        self.assertFalse(np.all(g == g2))
        self.assertEqual(g2.shape, g.shape)

    def test_write(self):
        outfilename = os.path.join(DATA_PATH, 'test_output/smooth_test.calfits')
        g = deepcopy(self.cs.gain_grids[54, 'Jxx'])
        self.cs.write_smoothed_cal(output_replace=('test_input/', 'test_output/smoothed_'),
                                   add_to_history='hello world', clobber=True, telescope_name='PAPER')
        for cal in self.cs.cals:
            new_cal = io.HERACal(cal.replace('test_input/', 'test_output/smoothed_'))
            gains, flags, _, _ = new_cal.read()
            self.assertTrue('helloworld' in new_cal.history.replace('\n', '').replace(' ', ''))
            self.assertTrue('Thisfilewasproducedbythefunction' in new_cal.history.replace('\n', '').replace(' ', ''))
            self.assertEqual(new_cal.telescope_name, 'PAPER')
            np.testing.assert_array_equal(gains[54, 'Jxx'], g[self.cs.time_indices[cal], :])
            os.remove(cal.replace('test_input/', 'test_output/smoothed_'))


if __name__ == '__main__':
    unittest.main()
