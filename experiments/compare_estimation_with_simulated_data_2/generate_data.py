# generate data for DCM-RNN and SPM estimation
import sys

# global setting, you need to modify it accordingly
if '/Users/yuanwang' in sys.executable:
    PROJECT_DIR = '/Users/yuanwang/Google_Drive/projects/Gits/DCM_RNN'
    print("It seems a local run on Yuan's laptop")
    print("PROJECT_DIR is set as: " + PROJECT_DIR)
    import matplotlib

    sys.path.append('dcm_rnn')
elif '/home/yw1225' in sys.executable:
    PROJECT_DIR = '/home/yw1225/projects/DCM_RNN'
    print("It seems a remote run on NYU HPC")
    print("PROJECT_DIR is set as: " + PROJECT_DIR)
    import matplotlib

    matplotlib.use('agg')
else:
    PROJECT_DIR = '.'
    print("Not sure executing machine. Make sure to set PROJECT_DIR properly.")
    print("PROJECT_DIR is set as: " + PROJECT_DIR)
    import matplotlib

import matplotlib.pyplot as plt
import tensorflow as tf
import tf_model as tfm
import toolboxes as tb
import numpy as np
import os
import pickle
import datetime
import warnings
import sys
import random
import training_manager
import multiprocessing
from multiprocessing.pool import Pool
import itertools
import copy
import pandas as pd
import math as mth
from scipy.interpolate import interp1d
import scipy as sp
import scipy.io

EXPERIMENT_PATH = os.path.join(PROJECT_DIR, 'experiments', 'compare_estimation_with_simulated_data_2')
DATA_PATH = os.path.join(EXPERIMENT_PATH, 'data')
CORE_PATH = os.path.join(DATA_PATH, 'core.pkl')
SAVE_PATH_PKL = os.path.join(DATA_PATH, 'du_DCM_RNN.pkl')
SAVE_PATH_MAT = os.path.join(DATA_PATH, 'DCM_initial.mat')
SNR = [1, 3, 5]
IF_RANDOM_HEMODYNAMIC_PARAMETER = False

du = tb.DataUnit()
du.u_amplitude = 1.
du._secured_data['if_random_neural_parameter'] = False
du._secured_data['if_random_hemodynamic_parameter'] = False
du._secured_data['if_random_x_state_initial'] = False
du._secured_data['if_random_h_state_initial'] = False
du._secured_data['if_random_stimuli'] = True
du._secured_data['if_random_node_number'] = False
du._secured_data['if_random_stimuli_number'] = False
du._secured_data['if_random_delta_t'] = False
du._secured_data['if_random_scan_time'] = False

du._secured_data['t_delta'] = 1. / 64.
du._secured_data['t_scan'] = 6 * 60
du._secured_data['n_node'] = 3
du._secured_data['n_stimuli'] = 2

du._secured_data['A'] = np.array([[-0.8, 0., 0.],
                                  [0.4, -0.8, 0.2],
                                  [0.2, 0.4, -0.8]])
du._secured_data['B'] = [np.array([[0, 0, 0],
                                   [0, 0, 0],
                                   [0, 0, -0.2]]),
                         np.array([[0., 0, 0],
                                   [0.4, 0, 0],
                                   [0, 0, 0]])]
du._secured_data['C'] = np.array([[0.4, 0., 0.], [0., 0, 0.]]).reshape(3, 2)

# designed input
'''
n_time_point = du.calculate_n_time_point(du.get('t_scan'), du.get('t_delta'))
t_duration = 20
u = np.zeros((n_time_point, du.get('n_stimuli')))
on_off_list = [(int(t_duration / du.get('t_delta') * 2 * i), int(t_duration / du.get('t_delta') * (2 * i + 1)))
          for i in range(int(np.floor(du.get('t_scan') / t_duration / 2)))]
for on_off in on_off_list:
    u[on_off[0]: on_off[1], 0] = 1
on_off_list = [(int(t_duration / du.get('t_delta') * 4 * i), int(t_duration / du.get('t_delta') * (4 * i + 2)))
          for i in range(int(np.floor(du.get('t_scan') / t_duration / 4)))]
for on_off in on_off_list:
    u[on_off[0]: on_off[1], 1] = 1
on_off_list = [(int(t_duration / du.get('t_delta') * 8 * i), int(t_duration / du.get('t_delta') * (8 * i + 4)))
          for i in range(int(np.floor(du.get('t_scan') / t_duration / 8)))]
du._secured_data['u'] = u
'''


# adjust hemodynamic parameter according to the ones used in SPM DCM
# with decay = 0 and transit = 0
# k = sd = H(1)*exp(decay) = 0.64
# gamma = H(2) = 0.32
# tao = tt = H(3)*exp(transit) = 2
# alpha = H(4) = 0.32
# E0 = H(5) = 0.4
# nu0 = theta0 = 40.3
# epsilon as in put P.epsilon, epsilon = exp(P.epsilon), initial of P.epsilon is 0
# in the latest development, the prior of hemodynamic parameters in toolboxes.Initialization been matched to the above settings
if IF_RANDOM_HEMODYNAMIC_PARAMETER:
    # in SPM12, only k, tao, and epsilon are configurable/trainable. As a result, only them are randomly sampled.
    hemodynamic_parameter = du.get_standard_hemodynamic_parameters(du.get('n_node'))
    temp = du.randomly_generate_hemodynamic_parameters(du.get('n_node'), 3)
    hemodynamic_parameter['k'] = temp['k']
    hemodynamic_parameter['tao'] = temp['tao']
    hemodynamic_parameter['epsilon'] = temp['epsilon']
else:
    hemodynamic_parameter = du.get_standard_hemodynamic_parameters(du.get('n_node'))
du._secured_data['hemodynamic_parameter'] = hemodynamic_parameter

# scan
du.complete_data_unit(if_show_message=False, if_check_property=False)

for i in range(du.get('n_node') + 1):
    plt.subplot(4, 1, i + 1)
    if i == 0:
        plt.plot(du.get('u'))
    else:
        plt.plot(du.get('y')[:, i - 1])

# add noise
for snr in SNR:
    noise_std = np.sqrt(np.var(du.get('y').flatten())) / snr
    noise = np.random.randn(du.get('y').shape[0], du.get('y').shape[1]) * noise_std
    du._secured_data['y_noised_snr_' + str(snr)] = du._secured_data['y'] + noise
for i in range(du.get('n_node') + 1):
    plt.subplot(4, 1, i + 1)
    if i == 0:
        plt.plot(du.get('u'))
    else:
        plt.plot(du.get('y_noised_snr_' + str(snr))[:, i - 1])


# save data
extra_data = ['y_noised_snr_' + str(snr) for snr in SNR]
core = du.collect_parameter_core(extra_data)
pickle.dump(core, open(CORE_PATH, 'wb'))


## do down sample and up sample, make the data used for DCM-RNN inference
# load data
core = tb.load_template(CORE_PATH)
du_original = tb.DataUnit()
du_original.load_parameter_core(core)
du_original.recover_data_unit()
extra_y = ['y_noised_snr_' + str(snr) for snr in SNR]
du = du_original.resample_data_unit(extra_y_keys=extra_y)
pickle.dump(du, open(SAVE_PATH_PKL, 'wb'))


# create DCM structure for SPM DCM
core = tb.load_template(CORE_PATH)
du = tb.DataUnit()
du.load_parameter_core(core)
du.recover_data_unit()
DCM = {}
DCM['u_original'] = du.get('u')
DCM['y_rnn_simulation'] = du.get('y')
extra_y = ['y_noised_snr_' + str(snr) for snr in SNR]
du = du_original.resample_data_unit(extra_y_keys=extra_y)
DCM['u_down_sampled'] = du.get('u')

mask = du.create_support_mask()
down_sample_rate_u = 1
# down_sample_rate_y = 128
down_sample_rate_y = 1
# covert to DCM needed by SPM

DCM['a'] = mask['Wxx']
DCM['b'] = np.stack(mask['Wxxu'], axis=2)
DCM['c'] = mask['Wxu']
DCM['v'] = float(du.get('n_time_point') / down_sample_rate_y)
DCM['n'] = float(du.get('n_node'))
DCM['TE'] = du.get('hemodynamic_parameter').iloc[0]['TE']
DCM['delays'] = np.zeros(3)
DCM['down_sample_rate_u'] = down_sample_rate_u
DCM['down_sample_rate_y'] = down_sample_rate_y

U = {}
U['dt'] = float(du.get('t_delta') * down_sample_rate_u)
U['name'] = ['input_0', 'input_1']
U['u'] = du.get('u')[::int(down_sample_rate_u), :]
DCM['U'] = U

Y = {}
Y['dt'] = float(du.get('t_delta') * down_sample_rate_y)
Y['y'] = du.get('y')[::int(down_sample_rate_y), :]
for snr in SNR:
    Y['y_noised_snr_' + str(snr)] = du.get('y_noised_snr_' + str(snr))[::int(down_sample_rate_y), :]
Y['name'] = ['node_0', 'node_1', 'node_2']
Y['Q'] = []
DCM['Y'] = Y

options = {}
options['nonlinear'] = 0.
options['two_state'] = 0.
options['stochastic'] = 0.
options['centre'] = 0.
options['induced'] = 0.
DCM['options'] = options

# None will case trouble
#if du.x_nonlinearity is None:
#    du.x_nonlinearity = 'None'
#if du._secured_data['scanner'].x_nonlinearity is None:
#    du._secured_data['scanner'].x_nonlinearity = 'None'

DCM['du'] = du
DCM['du_data'] = du._secured_data

DCM_initial = DCM
scipy.io.savemat(SAVE_PATH_MAT, mdict={'DCM_initial': DCM_initial})
