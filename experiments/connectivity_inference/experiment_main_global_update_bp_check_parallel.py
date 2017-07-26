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

def regenerate_data(du, Wxx, Wxxu, Wxu, h_parameters):
    du_hat = copy.deepcopy(du)
    du_hat._secured_data['n_node'] = 3
    du_hat._secured_data['n_stimuli'] = 3
    du_hat._secured_data['A'] = (Wxx - np.eye(du_hat.get('n_node'))) / dr.t_delta
    du_hat._secured_data['B'] = [Wxxu / dr.t_delta]
    du_hat._secured_data['C'] = Wxu / dr.t_delta

    du_hat._secured_data['t_delta'] = dr.t_delta

    hemodynamic_parameter_temp = du_hat.get_standard_hemodynamic_parameters(dr.n_region)
    temp = h_parameters
    for c in range(temp.shape[1]):
        hemodynamic_parameter_temp[hemodynamic_parameter_temp.columns[c]] = temp[:, c]
    du_hat._secured_data['hemodynamic_parameter_temp'] = hemodynamic_parameter_temp
    du_hat._secured_data['initial_x_state'] = du_hat.set_initial_neural_state_as_zeros(dr.n_region)
    du_hat._secured_data['initial_h_state'] = du_hat.set_initial_hemodynamic_state_as_inactivated(dr.n_region)
    del du_hat._secured_data['Wxx']
    del du_hat._secured_data['Wxxu']
    del du_hat._secured_data['Wxu']
    del du_hat._secured_data['Whh']
    del du_hat._secured_data['Whx']
    del du_hat._secured_data['bh']
    del du_hat._secured_data['Wo']
    del du_hat._secured_data['bo']

    del du_hat._secured_data['x']
    del du_hat._secured_data['h']
    del du_hat._secured_data['y']

    du_hat.complete_data_unit(start_categorty=1, if_check_property=False, if_show_message=False)
    return du_hat


def apply_and_check(isess, grads_and_vars, step_size, u, x_connector, h_connector, y_true):

    dr.update_variables_in_graph(isess, dr.trainable_variables_nodes,
                                 [-val[0] * step_size + val[1] for val in grads_and_vars])
    loss_prediction, x_connector, h_connector \
        = isess.run([dr.loss_prediction, dr.x_connector, dr.h_connector],
                    feed_dict={
                        dr.u_placeholder: u,
                        dr.x_state_initial: x_connector,
                        dr.h_state_initial: h_connector,
                        dr.y_true: y_true
                    })
    return [loss_prediction, x_connector, h_connector]


def check_transition_matrix(Wxx):
    w, v = np.linalg.eig(Wxx)
    if max(w.real) < 1:
        return True
    else:
        return False


MAX_EPOCHS = 120
CHECK_STEPS = 1
N_SEGMENTS = 1024
N_RECURRENT_STEP = 64
# STEP_SIZE = 0.002 # for 32
# STEP_SIZE = 0.5
# STEP_SIZE = 0.001 # for 64
# STEP_SIZE = 0.001 # 128
# STEP_SIZE = 0.0005 # for 256
STEP_SIZE = 1e-5
# DATA_SHIFT = int(N_RECURRENT_STEP / 4)
DATA_SHIFT = 1
LEARNING_RATE = 0.01 / N_RECURRENT_STEP


print('current working directory is ' + os.getcwd())
# PROJECT_DIR = '/Users/yuanwang/Google_Drive/projects/Gits/DCM_RNN'
data_path = PROJECT_DIR + "/dcm_rnn/resources/template0.pkl"
du = tb.load_template(data_path)

print('building model')
dr = tfm.DcmRnn()
dr.collect_parameters(du)
dr.learning_rate = LEARNING_RATE
dr.shift_data = DATA_SHIFT
dr.n_recurrent_step = N_RECURRENT_STEP
neural_parameter_initial = {'A': du.get('A'), 'B': du.get('B'), 'C': du.get('C')}
dr.loss_weighting = {'prediction': 1., 'sparsity': 0.1, 'prior': 10, 'Wxx': 1., 'Wxxu': 1., 'Wxu': 1.}
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
dr.build_main_graph(neural_parameter_initial=neural_parameter_initial)

# process after building the main graph
mask = {dr.Wxx.name: np.ones((dr.n_region, dr.n_region)),
        dr.Wxxu[0].name: np.zeros((dr.n_region, dr.n_region)),
        dr.Wxu.name: np.zeros(dr.n_region).reshape(3, 1)}
mask[dr.Wxxu[0].name][2, 2] = 1
mask[dr.Wxu.name][0] = 1
dr.support_masks = dr.setup_support_mask(mask)
dr.x_parameter_nodes = [v for v in tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES,
                    scope=dr.variable_scope_name_x_parameter)]
dr.trainable_variables_nodes = [v for v in tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES)]

# y_hat are re-generated after each global updating
# gradients of each segments are calculated all according to this y_hat
# namely, Wxx, Wxxu, and Wxu are not updated in each segment
Wxx = np.identity(3) * (1 - 1. * du.get('t_delta'))
Wxxu = np.zeros((3, 3))
Wxu = np.array([0., 0., 0.]).reshape(3, 1)
h_parameters = dr.get_standard_hemodynamic_parameters(dr.n_region)

du_hat = regenerate_data(du, Wxx, Wxxu, Wxu, np.array(h_parameters))

data_hat ={
    'x_initial': tb.split(du_hat.get('x'), n_segment=dr.n_recurrent_step, n_step=dr.shift_data, shift=0),
    'h_initial': tb.split(du_hat.get('h'), n_segment=dr.n_recurrent_step, n_step=dr.shift_data, shift=1),
}
data = {
    'u': tb.split(du.get('u'), n_segment=dr.n_recurrent_step, n_step=dr.shift_data),
    'x_initial': tb.split(du.get('x'), n_segment=dr.n_recurrent_step, n_step=dr.shift_data, shift=0),
    'h_initial': tb.split(du.get('h'), n_segment=dr.n_recurrent_step, n_step=dr.shift_data, shift=1),
    'x_whole': tb.split(du.get('x'), n_segment=dr.n_recurrent_step + dr.shift_u_x, n_step=dr.shift_data, shift=0),
    'h_whole': tb.split(du.get('h'), n_segment=dr.n_recurrent_step + dr.shift_x_y, n_step=dr.shift_data, shift=1),
    'h_predicted': tb.split(du.get('h'), n_segment=dr.n_recurrent_step, n_step=dr.shift_data, shift=dr.shift_u_y),
    'y_true': tb.split(du.get('y'), n_segment=dr.n_recurrent_step, n_step=dr.shift_data, shift=dr.shift_u_y),
    'y_true_float_corrected': []}
for k in data.keys():
    data[k] = data[k][: N_SEGMENTS]

for i in range(len(data['y_true'])):
    parameter_package = du.collect_parameter_for_y_scan()
    parameter_package['h'] = data['h_predicted'][i].astype(np.float32)
    data['y_true_float_corrected'].append(du.scan_y(parameter_package))

N_TEST_SAMPLE = min(N_SEGMENTS, len(data['y_true_float_corrected']))

print('start session')
# start session
isess = tf.InteractiveSession()

isess.run(tf.global_variables_initializer())
dr.update_variables_in_graph(isess, dr.x_parameter_nodes, [Wxx, Wxxu, Wxu])

print('start inference')
loss_differences = []
loss_totals = []
y_before_train = []
y_after_train = []
x_connectors = []
h_connectors = []
gradients = []
step_sizes = []
for epoch in range(MAX_EPOCHS):
    x_connector_current = dr.set_initial_neural_state_as_zeros(dr.n_region)
    h_connector_current = dr.set_initial_hemodynamic_state_as_inactivated(dr.n_region)
    gradients = []

    bar = progressbar.ProgressBar(max_value=N_TEST_SAMPLE)
    for i in range(len(data['y_true_float_corrected'])):
        # print('current processing ' + str(i))
        # print('.', end='')
        # bar.update(i)
        grads_and_vars, x_connector, h_connector, loss_prediction, loss_total, y_predicted_before_training = \
            isess.run([dr.grads_and_vars, dr.x_connector, dr.h_connector,
                       dr.loss_prediction, dr.loss_total, dr.y_predicted],
                      feed_dict={
                          dr.u_placeholder: data['u'][i],
                          # dr.x_state_initial: x_connector_current,
                          # dr.h_state_initial: h_connector_current,
                          dr.x_state_initial: data_hat['x_initial'][i][0, :],
                          dr.h_state_initial: data_hat['h_initial'][i][0, :, :],
                          dr.y_true: data['y_true_float_corrected'][i]
                      })

        # apply mask to gradients
        variable_names = [v.name for v in tf.trainable_variables()]
        for idx in range(len(grads_and_vars)):
            variable_name = variable_names[idx]
            grads_and_vars[idx] = (grads_and_vars[idx][0] * dr.support_masks[variable_name], grads_and_vars[idx][1])

        # collect gradients and logs
        gradients.append(grads_and_vars)
        loss_totals.append(loss_total)

        # prepare for next segment
        # x_connector_current = x_connector
        # h_connector_current = h_connector

    # updating with back-tracking
    ## collect statistics before updating
    Wxx, Wxxu, Wxu, h_parameters = isess.run([dr.Wxx, dr.Wxxu[0], dr.Wxu, dr.h_parameters])
    du_hat = regenerate_data(du, Wxx, Wxxu, Wxu, h_parameters)
    y_hat_original = du_hat.get('y')
    loss_prediction_original = tb.mse(y_hat_original, du.get('y'))

    ## sum gradients
    grads_and_vars = gradients[-1]
    for idx, grad_and_var in enumerate(grads_and_vars):
        grads_and_vars[idx] = (sum([gv[idx][0] for gv in gradients]), grads_and_vars[idx][1])


    step_size = STEP_SIZE
    count = 0

    dr.update_variables_in_graph(isess, dr.trainable_variables_nodes,
                                 [-val[0] * step_size + val[1] for val in grads_and_vars])
    Wxx, Wxxu, Wxu, h_parameters = isess.run([dr.Wxx, dr.Wxxu[0], dr.Wxu, dr.h_parameters])
    try:
        du_hat = regenerate_data(du, Wxx, Wxxu, Wxu, h_parameters)
        y_hat = du_hat.get('y')
        loss_prediction = tb.mse(y_hat, du.get('y'))
    except:
        loss_prediction = float('inf')

    Wxx = isess.run(dr.Wxx)
    stable_flag = check_transition_matrix(Wxx)
    while not stable_flag:
        count += 1
        if count == 20:
            step_size = 0
        else:
            step_size = step_size / 2
        warnings.warn('not stable')
        print('step_size=' + str(step_size))
        Wxx = -grads_and_vars[0][0] * step_size + grads_and_vars[0][1]
        stable_flag = check_transition_matrix(Wxx)

    while loss_prediction > loss_prediction_original or np.isnan(loss_prediction):
        count += 1
        if count == 20:
            step_size = 0.
        else:
            step_size = step_size / 2
        print('step_size=' + str(step_size))
        try:
            dr.update_variables_in_graph(isess, dr.trainable_variables_nodes,
                                         [-val[0] * step_size + val[1] for val in grads_and_vars])
            Wxx, Wxxu, Wxu, h_parameters = isess.run([dr.Wxx, dr.Wxxu[0], dr.Wxu, dr.h_parameters])
            du_hat = regenerate_data(du, Wxx, Wxxu, Wxu, h_parameters)
            y_hat = du_hat.get('y')
            loss_prediction = tb.mse(y_hat, du.get('y'))
        except:
            pass
        if step_size == 0.0:
            break

    loss_differences.append(loss_prediction_original - loss_prediction)
    step_sizes.append(step_size)

    # regenerate connector data
    data_hat['x_initial'] = tb.split(du_hat.get('x'), n_segment=dr.n_recurrent_step, n_step=dr.shift_data, shift=0)
    data_hat['h_initial'] = tb.split(du_hat.get('h'), n_segment=dr.n_recurrent_step, n_step=dr.shift_data, shift=1)


    print(step_size)
    print(loss_prediction_original)
    print(loss_differences[-1])
    print(Wxx)
    print(Wxxu)
    print(Wxu)


print('optimization finished.')

i = 0
plt.plot(y_hat[:, i], '--')
plt.plot(du.get('y')[:, i])