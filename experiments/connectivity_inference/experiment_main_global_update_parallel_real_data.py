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
import progressbar
import math as mth
import re
import importlib
from scipy.interpolate import interp1d


MAX_EPOCHS = 36
CHECK_STEPS = 1
N_RECURRENT_STEP = 128
DATA_SHIFT = 4
MAX_BACK_TRACK = 8
MAX_CHANGE = 0.004
TARGET_TEMPORAL_RESOLUTION = 1. / 16
BATCH_RANDOM_DROP_RATE = 0.5


print('current working directory is ' + os.getcwd())
# importlib.reload(tb)
DATA_DIR = os.path.join(PROJECT_DIR, 'dcm_rnn', 'resources', 'SPM_data_attention.pkl')
spm_data = pickle.load(open(DATA_DIR, 'rb'))
# process spm_data,
# up sample u and y to 16 frame/second
# shift y's so that they are around 0 when there is no input
t_total = spm_data['TR'] * spm_data['y'].shape[0]
t_axis_original = np.linspace(0, t_total, int(t_total / spm_data['TR']), endpoint=True)
t_axis_new = np.linspace(0, t_total, int(t_total / TARGET_TEMPORAL_RESOLUTION), endpoint=True)
spm_data['y_upsampled'] = np.zeros((len(t_axis_new), spm_data['y'].shape[1]))
for i in range(spm_data['y'].shape[1]):
    interpolate_func = interp1d(t_axis_original, spm_data['y'][:, i], kind='cubic')
    spm_data['y_upsampled'][:, i] = interpolate_func(t_axis_new)
spm_data['u_upsampled'] = np.zeros((len(t_axis_new), spm_data['u'].shape[1]))
for i in range(spm_data['u'].shape[1]):
    interpolate_func = interp1d(t_axis_original, spm_data['u'][:, i])
    spm_data['u_upsampled'][:, i] = interpolate_func(t_axis_new)
temporal_mask = spm_data['u_upsampled'][:, 0] < 0.5
temp = copy.deepcopy(spm_data['y_upsampled'])
mean_values = np.mean(temp[temporal_mask, :], axis=0)
mean_values = np.repeat(mean_values.reshape([1, 3]), spm_data['y_upsampled'].shape[0], axis=0)
spm_data['y_upsampled'] = spm_data['y_upsampled'] - mean_values
N_SEGMENTS = mth.ceil(len(spm_data['y_upsampled']) / N_RECURRENT_STEP) * N_RECURRENT_STEP


# build DataUnit du from spm_data
du = tb.DataUnit()
du._secured_data['n_node'] = spm_data['y_upsampled'].shape[1]
du._secured_data['n_stimuli'] = spm_data['u_upsampled'].shape[1]
du._secured_data['t_delta'] = TARGET_TEMPORAL_RESOLUTION
du._secured_data['t_scan'] = du._secured_data['t_delta'] * spm_data['y_upsampled'].shape[0]
du._secured_data['n_time_point'] = spm_data['y_upsampled'].shape[0]
du._secured_data['u'] = spm_data['u_upsampled']
du._secured_data['y'] = spm_data['y_upsampled']


# initialize DataUnit du_hat, support masks should be specified here
# Wxx = np.zeros((du.get('n_node'), du.get('n_node')))
Wxx = np.eye(du.get('n_node')) - np.eye(du.get('n_node')) * du.get('t_delta')
Wxxu = [np.zeros((du.get('n_node'), du.get('n_node'))) for _ in range(du.get('n_stimuli'))]
Wxu = np.zeros((du.get('n_node'), du.get('n_stimuli')))
Wxu[0, 0] = 1. * du.get('t_delta')
h_parameters = du.get_standard_hemodynamic_parameters(du.get('n_node'))
h_parameters['x_h_coupling'] = 1.
mask = {
    'Wxx': np.ones((du.get('n_node'), du.get('n_node'))),
    'Wxxu': [np.zeros((du.get('n_node'), du.get('n_node'))) for _ in range(du.get('n_stimuli'))],
    'Wxu': np.zeros((du.get('n_node'), du.get('n_stimuli')))
}
mask['Wxx'][0, 2] = 0
mask['Wxx'][2, 0] = 0
mask['Wxxu'][1][1, 0] = 1
mask['Wxxu'][2][0, 1] = 1
mask['Wxu'][0, 0] = 1
du_hat = du.initialize_a_training_unit(Wxx, Wxxu, Wxu, np.array(h_parameters))



# build tensorflow model
print('building model')
dr = tfm.DcmRnn()
dr.collect_parameters(du)
dr.shift_data = DATA_SHIFT
dr.n_recurrent_step = N_RECURRENT_STEP
dr.max_back_track_steps = MAX_BACK_TRACK
dr.max_parameter_change_per_iteration = MAX_CHANGE
neural_parameter_initial = {'A': du_hat.get('A'), 'B': du_hat.get('B'), 'C': du_hat.get('C')}
dr.loss_weighting = {'prediction': 1., 'sparsity': 1, 'prior': 1, 'Wxx': 1., 'Wxxu': 0., 'Wxu': 0.}
dr.trainable_flags = {'Wxx': True,
                      'Wxxu': True,
                      'Wxu': True,
                      'alpha': True,
                      'E0': True,
                      'k': True,
                      'gamma': True,
                      'tao': True,
                      'epsilon': False,
                      'V0': False,
                      'TE': False,
                      'r0': False,
                      'theta0': False,
                      'x_h_coupling': False
                      }
dr.build_main_graph_parallel(neural_parameter_initial=neural_parameter_initial)


# process after building the main graph
dr.support_masks = dr.setup_support_mask(mask)
dr.x_parameter_nodes = [v for v in tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES,
                                                     scope=dr.variable_scope_name_x_parameter)]
dr.trainable_variables_nodes = [v for v in tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES)]
dr.trainable_variables_names = [v.name for v in tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES)]
du_hat.variable_names_in_graph = du_hat.parse_variable_names(dr.trainable_variables_names)


# prepare data for training
data_hat = {
    'x_initial': tb.split(du_hat.get('x'), n_segment=dr.n_recurrent_step, n_step=dr.shift_data, shift=0),
    'h_initial': tb.split(du_hat.get('h'), n_segment=dr.n_recurrent_step, n_step=dr.shift_data, shift=1),
}
data = {
    'u': tb.split(du.get('u'), n_segment=dr.n_recurrent_step, n_step=dr.shift_data),
    'y': tb.split(du.get('y'), n_segment=dr.n_recurrent_step, n_step=dr.shift_data, shift=dr.shift_u_y)}
for k in data_hat.keys():
    data[k] = data_hat[k][: N_SEGMENTS]
for k in data.keys():
    data[k] = data[k][: N_SEGMENTS]
batches = tb.make_batches(data['u'], data_hat['x_initial'], data_hat['h_initial'], data['y'],
                          batch_size=dr.batch_size, if_shuffle=True)

print('start session')
# start session
isess = tf.InteractiveSession()
isess.run(tf.global_variables_initializer())
dr.update_variables_in_graph(isess, dr.x_parameter_nodes, [Wxx] + Wxxu + [Wxu])

print('start inference')
loss_differences = []
step_sizes = []
for epoch in range(MAX_EPOCHS):
    print('')
    print('epoch:    ' + str(epoch))
    gradients = []

    bar = progressbar.ProgressBar(max_value=len(batches))
    for batch in batches:
        grads_and_vars = \
            isess.run(dr.grads_and_vars,
                      feed_dict={
                          dr.u_placeholder: batch['u'],
                          dr.x_state_initial: batch['x_initial'],
                          dr.h_state_initial: batch['h_initial'],
                          dr.y_true: batch['y']
                      })
        # apply mask to gradients
        variable_names = [v.name for v in tf.trainable_variables()]
        for idx in range(len(grads_and_vars)):
            variable_name = variable_names[idx]
            grads_and_vars[idx] = (grads_and_vars[idx][0] * dr.support_masks[variable_name], grads_and_vars[idx][1])

        # collect gradients and logs
        gradients.append(grads_and_vars)

    # updating with back-tracking
    ## collect statistics before updating
    # xx, Wxxu, Wxu, h_parameter_initial = isess.run([dr.Wxx, dr.Wxxu[0], dr.Wxu, dr.h_parameter_initial])
    # du_hat = regenerate_data(du, Wxx, Wxxu, Wxu, h_parameter_initial)

    du_hat.update_trainable_variables(grads_and_vars, step_size=0)
    du_hat.regenerate_data()

    y_hat_original = du_hat.get('y')
    loss_prediction_original = tb.mse(y_hat_original, du.get('y'))

    ## sum gradients
    grads_and_vars = gradients[-1]
    for idx, grad_and_var in enumerate(grads_and_vars):
        grads_and_vars[idx] = (sum([gv[idx][0] for gv in gradients]), grads_and_vars[idx][1])

    # adaptive step size, making max value change dr.max_parameter_change_per_iteration
    max_gradient = max([np.max(np.abs(np.array(g[0])).flatten()) for g in grads_and_vars])
    STEP_SIZE = dr.max_parameter_change_per_iteration / max_gradient
    print('max gradient:    ' + str(max_gradient))
    print('STEP_SIZE:    ' + str(STEP_SIZE))

    # try to find proper step size
    step_size = STEP_SIZE
    count = 0
    du_hat.update_trainable_variables(grads_and_vars, step_size)

    Wxx = du_hat.get('Wxx')
    stable_flag = du.check_transition_matrix(Wxx, 1.)
    while not stable_flag:
        count += 1
        if count == dr.max_back_track_steps:
            step_size = 0.
            dr.decrease_max_parameter_change_per_iteration()
        else:
            step_size = step_size / 2
        warnings.warn('not stable')
        print('step_size=' + str(step_size))
        du_hat.update_trainable_variables(grads_and_vars, step_size)
        Wxx = du_hat.get('Wxx')
        stable_flag = du.check_transition_matrix(Wxx, 1.)

    try:
        # du_hat = regenerate_data(du, Wxx, Wxxu, Wxu, h_parameter_initial)
        du_hat.regenerate_data()
        y_hat = du_hat.get('y')
        loss_prediction = tb.mse(y_hat, du.get('y'))
    except:
        loss_prediction = float('inf')

    while loss_prediction > loss_prediction_original or np.isnan(loss_prediction):
        count += 1
        if count == dr.max_back_track_steps:
            step_size = 0.
            dr.decrease_max_parameter_change_per_iteration()
        else:
            step_size = step_size / 2
        print('step_size=' + str(step_size))
        try:
            '''
            dr.update_variables_in_graph(isess, dr.trainable_variables_nodes,
                                         [-val[0] * step_size + val[1] for val in grads_and_vars])
            Wxx, Wxxu, Wxu, h_parameter_initial = isess.run([dr.Wxx, dr.Wxxu[0], dr.Wxu, dr.h_parameter_initial])
            du_hat = regenerate_data(du, Wxx, Wxxu, Wxu, h_parameter_initial)
            '''

            du_hat.update_trainable_variables(grads_and_vars, step_size)
            du_hat.regenerate_data()
            y_hat = du_hat.get('y')
            loss_prediction = tb.mse(y_hat, du.get('y'))
        except:
            pass
        if step_size == 0.0:
            break

    # update parameters in graph with found step_size
    if step_size > 0:
        dr.update_variables_in_graph(isess, dr.trainable_variables_nodes,
                                     [-val[0] * step_size + val[1] for val in grads_and_vars])

    loss_differences.append(loss_prediction_original - loss_prediction)
    step_sizes.append(step_size)

    # regenerate connector data
    data_hat['x_initial'] = tb.split(du_hat.get('x'), n_segment=dr.n_recurrent_step, n_step=dr.shift_data, shift=0)
    data_hat['h_initial'] = tb.split(du_hat.get('h'), n_segment=dr.n_recurrent_step, n_step=dr.shift_data, shift=1)
    batches = tb.make_batches(data['u'], data_hat['x_initial'],
                              data_hat['h_initial'], data['y'],
                              batch_size=dr.batch_size,
                              if_shuffle=True)
    batches = tb.random_drop(batches, ration=BATCH_RANDOM_DROP_RATE)
    print('applied step size:    ' + str(step_size))
    print('loss_prediction_original:    ' + str(loss_prediction_original))
    print('reduced prediction:    ' + str(loss_differences[-1]))
    print('reduced prediction persentage:    ' + str(loss_differences[-1] / loss_prediction_original))
    print(du_hat.get('Wxx'))
    print(du_hat.get('Wxxu'))
    print(du_hat.get('Wxu'))
    # print(h_parameter_initial)


print('optimization finished.')

i = 2
plt.plot(du.get('y')[:, i])
plt.plot(du_hat.get('y')[:, i], '--')
