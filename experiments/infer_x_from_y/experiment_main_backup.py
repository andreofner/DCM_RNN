import sys
# global setting, you need to modify it accordingly
if '/Users/yuanwang' in sys.executable:
    PROJECT_DIR = '/Users/yuanwang/Google_Drive/projects/Gits/DCM_RNN'
    print("It seems a local run on Yuan's laptop")
    print("PROJECT_DIR is set as: " + PROJECT_DIR)
    import matplotlib
    sys.path.append('dcm_rnn')
elif '/share/apps/python3/' in sys.executable:
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



def get_log_prefix(extra_prefix=''):
    prefix = extra_prefix \
             + 'nodeNumber' + str(dr.n_region) \
             + '_segments' + str(N_SEGMENTS) \
             + '_learningRate' + str(dr.learning_rate).replace('.', 'p') \
             + '_recurrentStep' + str(N_RECURRENT_STEP) \
             + '_dataShift' + str(DATA_SHIFT) \
             + '_iteration' + str(count_total)
    return prefix


def prepare_data(max_segments=None, node_index=None):
    global data
    global loss_x_normalizer
    global loss_y_normalizer
    global loss_smooth_normalizer
    global isess

    global SEQUENCE_LENGTH
    global H_STATE_INITIAL
    global IF_NOISED_Y
    global SNR
    global NOISE

    if IF_NOISED_Y:
        std = np.std(du.get('y').reshape([-1])) / SNR
        NOISE = np.random.normal(0, std, du.get('y').shape)
    else:
        NOISE = np.zeros(du.get('y').shape)

    ## saved line. SEQUENCE_LENGTH = dr.n_recurrent_step + (len(spm_data['x_true']) - 1) * dr.shift_data
    data['y_train'] = tb.split(du.get('y') + NOISE, dr.n_recurrent_step, dr.shift_data, dr.shift_x_y)
    max_segments_natural = len(data['y_train'])
    data['y_true'] = tb.split(du.get('y'), dr.n_recurrent_step, dr.shift_data, dr.shift_x_y)[:max_segments_natural]
    data['h_true_monitor'] = tb.split(du.get('h'), dr.n_recurrent_step, dr.shift_data)[:max_segments_natural]
    data['x_true'] = tb.split(du.get('x'), dr.n_recurrent_step, dr.shift_data)[:max_segments_natural]
    data['u'] = tb.split(du.get('u'), dr.n_recurrent_step, dr.shift_data)[:max_segments_natural]

    if max_segments is not None:
        if max_segments > max_segments_natural:
            warnings.warn("max_segments is larger than the length of available spm_data", UserWarning)
        else:
            data['u'] = data['u'][:max_segments]
            data['x_true'] = data['x_true'][:max_segments]
            data['h_true_monitor'] = data['h_true_monitor'][:max_segments]
            data['y_true'] = data['y_true'][:max_segments]
            data['y_train'] = data['y_train'][:max_segments]

    if node_index is not None:
        data['x_true'] = [array[:, node_index].reshape(dr.n_recurrent_step, 1) for array in data['x_true']]
        data['h_true_monitor'] = [np.take(array, node_index, 1) for array in data['h_true_monitor']]
        data['y_true'] = [array[:, node_index].reshape(dr.n_recurrent_step, 1) for array in data['y_true']]
        data['y_train'] = [array[:, node_index].reshape(dr.n_recurrent_step, 1) for array in data['y_train']]
        H_STATE_INITIAL = H_STATE_INITIAL[node_index].reshape(1, 4)

    # collect merged spm_data (without split and merge, it can be tricky to cut proper part from du)
    data['u_merged'] = tb.merge(data['u'], dr.n_recurrent_step, dr.shift_data)
    data['x_true_merged'] = tb.merge(data['x_true'], dr.n_recurrent_step, dr.shift_data)
    # x_hat is with extra wrapper for easy modification with a single index
    data['x_hat_merged'] = tb.ArrayWrapper(np.zeros(data['x_true_merged'].shape), dr.n_recurrent_step, dr.shift_data)
    data['h_true_monitor_merged'] = tb.merge(data['h_true_monitor'], dr.n_recurrent_step, dr.shift_data)
    data['y_true_merged'] = tb.merge(data['y_true'], dr.n_recurrent_step, dr.shift_data)
    data['y_train_merged'] = tb.merge(data['y_train'], dr.n_recurrent_step, dr.shift_data)

    # run forward pass with x_true to show y error caused by error in the network parameters
    isess.run(tf.global_variables_initializer())
    y_hat_x_true_log, h_hat_x_true_monitor_log, h_hat_x_true_connector_log = \
        dr.run_initializer_graph(isess, H_STATE_INITIAL, data['x_true'])
    data['h_hat_x_true_monitor'] = h_hat_x_true_monitor_log
    data['y_hat_x_true'] = y_hat_x_true_log
    data['h_hat_x_true_monitor_merged'] = tb.merge(h_hat_x_true_monitor_log, dr.n_recurrent_step, dr.shift_data)
    data['y_hat_x_true_merged'] = tb.merge(y_hat_x_true_log, dr.n_recurrent_step, dr.shift_data)

    loss_x_normalizer = np.sum(data['x_true_merged'].flatten() ** 2)
    loss_y_normalizer = np.sum(data['y_true_merged'].flatten() ** 2)
    loss_smooth_normalizer = np.std(data['x_true_merged'].flatten()) ** 2

    return data


def calculate_log_data():
    global isess

    if 'y_hat_x_true' not in data.keys():
        # run forward pass with x_true to show y error caused by error in the network parameters
        with tf.Session() as sess:
            sess.run(tf.global_variables_initializer())
            y_hat_x_true_log, h_hat_x_true_monitor_log, h_hat_x_true_connector_log = \
                dr.run_initializer_graph(sess, H_STATE_INITIAL, data['x_true'])

        data['h_hat_x_true_monitor'] = h_hat_x_true_monitor_log
        data['y_hat_x_true'] = y_hat_x_true_log
        data['h_hat_x_true_monitor_merged'] = tb.merge(h_hat_x_true_monitor_log, dr.n_recurrent_step, dr.shift_data)
        data['y_hat_x_true_merged'] = tb.merge(y_hat_x_true_log, dr.n_recurrent_step, dr.shift_data)

        data['loss_x_normalizer'] = np.sum(data['x_true_merged'].flatten() ** 2)
        data['loss_y_normalizer'] = np.sum(data['y_true_merged'].flatten() ** 2)
        data['loss_smooth_normalizer'] = np.std(data['x_true_merged'].flatten()) ** 2

    data['x_hat'] = tb.split(data['x_hat_merged'].get(), n_segment=dr.n_recurrent_step, n_step=dr.shift_data)
    if IF_NODE_MODE:
        data['x_hat'] = [array.reshape(dr.n_recurrent_step, 1) for array in data['x_hat']]

    isess.run(tf.global_variables_initializer())
    y_hat_log, h_hat_monitor_log, h_hat_connector_log = \
        dr.run_initializer_graph(isess, H_STATE_INITIAL, data['x_hat'])

    # collect results
    # segmented spm_data
    data['x_hat'] = data['x_hat']
    data['x_true'] = data['x_true']

    data['h_true_monitor'] = data['h_true_monitor']
    data['h_hat_x_true_monitor'] = data['h_hat_x_true_monitor']
    data['h_hat_monitor'] = h_hat_monitor_log

    data['y_train'] = data['y_train']
    data['y_true'] = data['y_true']
    data['y_hat_x_true'] = data['y_hat_x_true']
    data['y_hat'] = y_hat_log

    # merged spm_data
    data['x_true_merged'] = data['x_true_merged']
    data['x_hat_merged'] = data['x_hat_merged']

    data['h_true_monitor_merged'] = data['h_true_monitor_merged']
    data['h_hat_x_true_monitor_merged'] = data['h_hat_x_true_monitor_merged']
    data['h_hat_monitor_merged'] = tb.merge(h_hat_monitor_log, dr.n_recurrent_step, dr.shift_data)

    data['y_train_merged'] = data['y_train_merged']
    data['y_true_merged'] = data['y_true_merged']
    data['y_hat_x_true_merged'] = data['y_hat_x_true_merged']
    data['y_hat_merged'] = tb.merge(y_hat_log, dr.n_recurrent_step, dr.shift_data)

    # calculate loss
    loss_x = np.sum((data['x_hat_merged'].data.flatten() - data['x_true_merged'].flatten()) ** 2)
    loss_y = np.sum((data['y_hat_merged'].flatten() - data['y_true_merged'].flatten()) ** 2)
    loss_smooth = np.sum((data['x_hat_merged'].data[0:-1].flatten() - data['x_hat_merged'].data[1:].flatten()) ** 2)

    data['loss_x'].append(loss_x / loss_x_normalizer)
    data['loss_y'].append(loss_y / loss_y_normalizer)
    data['loss_smooth'].append(loss_smooth / loss_smooth_normalizer)
    data['loss_total'].append((loss_y + dr.loss_weighting['smooth'] * loss_smooth) / (
        loss_y_normalizer + dr.loss_weighting['smooth'] * loss_smooth_normalizer))


def add_image_log(image_log_dir='./image_logs/', extra_prefix=''):
    global IF_NOISED_Y
    if not os.path.exists(image_log_dir):
        os.makedirs(image_log_dir)
    log_file_name_prefix = get_log_prefix(extra_prefix)

    plt.figure(figsize=(10, 10))
    plt.subplot(2, 2, 1)
    plt.plot(data['x_true_merged'], label='x_true')
    plt.plot(data['x_hat_merged'].get(), '--', label='x_hat')
    plt.xlabel('time')
    plt.ylabel('signal')
    plt.title('Iter = ' + str(count_total))
    plt.legend()

    if IF_NOISED_Y:
        plt.subplot(2, 2, 2)
        plt.plot(data['y_train_merged'], label='y_train', alpha=0.5)
        plt.plot(data['y_true_merged'], label='y_true')
        plt.plot(data['y_hat_merged'], '--', label='y_hat')
        plt.xlabel('time')
        plt.ylabel('signal')
        plt.title('Iter = ' + str(count_total))
        plt.legend()
    else:
        plt.subplot(2, 2, 2)
        plt.plot(data['y_true_merged'], label='y_true')
        plt.plot(data['y_hat_merged'], '--', label='y_hat')
        plt.xlabel('time')
        plt.ylabel('signal')
        plt.title('Iter = ' + str(count_total))
        plt.legend()

    plt.subplot(2, 2, 3)
    plt.plot(data['y_true_merged'], label='by net_true')
    plt.plot(data['y_hat_x_true_merged'], '--', label='by net_hat')
    plt.xlabel('time')
    plt.ylabel('signal')
    plt.title('y reproduced with x_true, iter = ' + str(count_total))
    plt.legend()

    plt.subplot(2, 2, 4)
    plt.plot(data['loss_x'], '--', label='x loss')
    plt.plot(data['loss_y'], '-.', label='y loss')
    # plt.plot(spm_data['loss_smooth'], label='smooth loss')
    plt.plot(data['loss_total'], label='total loss')
    plt.xlabel('check point index')
    plt.ylabel('value')
    plt.title('Normalized loss, iter = ' + str(count_total))
    plt.legend()

    plt.tight_layout()
    plot_file_name = image_log_dir + log_file_name_prefix + '.png'
    plt.savefig(plot_file_name)
    plt.close()


def add_data_log(data_log_dir='./data_logs/', extra_prefix=''):
    if not os.path.exists(data_log_dir):
        os.makedirs(data_log_dir)

    log_file_name_prefix = get_log_prefix(extra_prefix)

    data_saved = {}

    data_saved['IF_RANDOM_H_PARA'] = IF_RANDOM_H_PARA
    data_saved['IF_RANDOM_H_STATE_INIT'] = IF_RANDOM_H_STATE_INIT
    data_saved['IF_NOISED_Y'] = IF_NOISED_Y
    data_saved['IF_NODE_MODE'] = IF_NODE_MODE
    data_saved['IF_IMAGE_LOG'] = IF_IMAGE_LOG
    data_saved['IF_DATA_LOG'] = IF_DATA_LOG

    data_saved['NODE_INDEX'] = NODE_INDEX
    data_saved['MAX_EPOCHS'] = MAX_EPOCHS
    data_saved['MAX_EPOCHS_INNER'] = MAX_EPOCHS_INNER
    data_saved['n_segments'] = N_SEGMENTS
    data_saved['CHECK_STEPS'] = CHECK_STEPS

    data_saved['N_RECURRENT_STEP'] = N_RECURRENT_STEP
    data_saved['LEARNING_RATE'] = LEARNING_RATE
    data_saved['DATA_SHIFT'] = DATA_SHIFT
    data_saved['SNR'] = SNR
    data_saved['LOG_EXTRA_PREFIX'] = LOG_EXTRA_PREFIX

    data_saved['SMOOTH_WEIGHT'] = SMOOTH_WEIGHT

    data_saved['iteration'] = count_total
    data_saved.update(data)

    file_name = data_log_dir + log_file_name_prefix + '.pkl'
    pickle.dump(data_saved, open(file_name, "wb"))


# global setting
IF_RANDOM_H_PARA = False
IF_RANDOM_H_STATE_INIT = False
IF_NOISED_Y = False

IF_NODE_MODE = True
IF_IMAGE_LOG = True
IF_DATA_LOG = True

SNR = 3
NODE_INDEX = 0
SMOOTH_WEIGHT = 0.
N_RECURRENT_STEP = 64
MAX_EPOCHS = 3
MAX_EPOCHS_INNER = 4
N_SEGMENTS = 256  # total amount of spm_data segments
# CHECK_STEPS = 4
# CHECK_STEPS = N_SEGMENTS * MAX_EPOCHS_INNER
CHECK_STEPS = N_SEGMENTS
LEARNING_RATE = 128 / N_RECURRENT_STEP
DATA_SHIFT = 4
LOG_EXTRA_PREFIX = ''

# load in spm_data
current_dir = os.getcwd()
print('working directory is ' + current_dir)
if current_dir.split('/')[-1] == "dcm_rnn":
    sys.path.append(current_dir)
    # os.chdir(current_dir + '/..')
    data_path = "../resources/template0.pkl"
elif current_dir.split('/')[-1] == "DCM_RNN":
    sys.path.append('dcm_rnn')
    data_path = "dcm_rnn/resources/template0.pkl"
elif current_dir.split('/')[-1] == "infer_x_from_y":
    data_path = "../../dcm_rnn/resources/template0.pkl"
else:
    # on HPC
    data_path = "/home/yw1225/projects/DCM_RNN/dcm_rnn/resources/template0.pkl"
du = tb.load_template(data_path)
print('Loading spm_data done.')

# build model
dr = tfm.DcmRnn()
dr.collect_parameters(du)
dr.learning_rate = LEARNING_RATE
dr.shift_data = DATA_SHIFT
dr.n_recurrent_step = N_RECURRENT_STEP
dr.loss_weighting['smooth'] = SMOOTH_WEIGHT
if IF_NODE_MODE:
    dr.n_region = 1
for key in dr.trainable_flags.keys():
    # in the initialization graph, the hemodynamic parameters are not trainable
    dr.trainable_flags[key] = False
if IF_RANDOM_H_PARA:
    H_PARA_INITIAL = \
        dr.randomly_generate_hemodynamic_parameters(dr.n_region, deviation_constraint=2).astype(np.float32)
else:
    H_PARA_INITIAL = dr.get_standard_hemodynamic_parameters(n_node=dr.n_region).astype(np.float32)
if IF_RANDOM_H_STATE_INIT:
    H_STATE_INITIAL = du.get('h')[random.randint(64, du.get('h').shape[0] - 64)].astype(np.float32)
else:
    H_STATE_INITIAL = dr.set_initial_hemodynamic_state_as_inactivated(n_node=dr.n_region).astype(np.float32)

dr.build_an_initializer_graph(hemodynamic_parameter_initial=H_PARA_INITIAL)
print('Building tf model done.')

# prepare spm_data
data = {}
isess = tf.InteractiveSession()     # for calculate loss during training
if IF_NODE_MODE:
    prepare_data(max_segments=N_SEGMENTS, node_index=NODE_INDEX)
else:
    prepare_data(max_segments=N_SEGMENTS)
print('Data preparation done.')

# training
print('Start training.')
x_hat_previous = data['x_hat_merged'].data.copy()
data['loss_x'] = []
data['loss_y'] = []
data['loss_smooth'] = []
data['loss_total'] = []
count_total = 0

data['x_hat_merged'].data = np.random.rand(1084, 1)

with tf.Session() as sess:
    for epoch in range(MAX_EPOCHS):
        sess.run(tf.global_variables_initializer())
        h_initial_segment = H_STATE_INITIAL
        sess.run(tf.assign(dr.x_state_stacked_previous, data['x_hat_merged'].get(0)))
        for i_segment in range(N_SEGMENTS):

            for epoch_inner in range(MAX_EPOCHS_INNER):
                # assign proper spm_data
                if IF_NODE_MODE is True:
                    sess.run([tf.assign(dr.x_state_stacked,
                                        data['x_hat_merged'].get(i_segment).reshape(dr.n_recurrent_step, 1)),
                              tf.assign(dr.h_state_initial, h_initial_segment)])
                else:
                    sess.run([tf.assign(dr.x_state_stacked, data['x_hat_merged'].get(i_segment)),
                              tf.assign(dr.h_state_initial, h_initial_segment)])

                # training
                sess.run(dr.train, feed_dict={dr.y_true: data['y_train'][i_segment]})

                # collect results
                temp = sess.run(dr.x_state_stacked)
                data['x_hat_merged'].set(i_segment, temp)

                # add noise, just for show equivalent x's
                # i_segment_temp = min(N_SEGMENTS - 1, i_segment + 1)
                # data['x_hat_merged'].set(i_segment_temp, np.mean(temp))
                # data['x_hat_merged'].set(i_segment, temp)

                # add counting
                count_total += 1

                # Display logs per CHECK_STEPS step
                if count_total % CHECK_STEPS == 0:
                    calculate_log_data()

                    # saved summary = sess.run(dr.merged_summary)
                    # saved dr.summary_writer.add_summary(summary, count_total)

                    print("Total iteration:", '%04d' % count_total, "loss_y=", "{:.9f}".format(data['loss_y'][-1]))
                    print("Total iteration:", '%04d' % count_total, "loss_x=", "{:.9f}".format(data['loss_x'][-1]))

                    if IF_IMAGE_LOG:
                        add_image_log(extra_prefix=LOG_EXTRA_PREFIX)

                    if IF_DATA_LOG:
                        add_data_log(extra_prefix=LOG_EXTRA_PREFIX)

                    '''
                    # check stop criterion
                    relative_change = tb.rmse(x_hat_previous, spm_data['x_hat_merged'].get())
                    if relative_change < dr.stop_threshold:
                        print('Relative change: ' + str(relative_change))
                        print('Stop criterion met, stop training')
                    else:
                        # x_hat_previous = copy.deepcopy(spm_data['x_hat_merged'])
                        x_hat_previous = spm_data['x_hat_merged'].get().copy()
                    '''

            # prepare for next segment
            # update hemodynamic state initial
            h_initial_segment = sess.run(dr.h_connector)
            # update previous neural state
            sess.run(tf.assign(dr.x_state_stacked_previous, data['x_hat_merged'].get(i_segment)))

# isess.close()
print("Optimization Finished!")

if not IF_NODE_MODE:
    # only the middle part of x_hat to estimate effective connection
    n_time_poine = data['x_hat_merged'].get().shape[0]
    start_point = int(n_time_poine / 4)
    end_point = int(n_time_poine * 3 / 4)
    x_hat_truncated = data['x_hat_merged'].get()[start_point: end_point]
    u_truncated = data['u_merged'][start_point: end_point]
    W_hat = tb.solve_for_effective_connection(x_hat_truncated, u_truncated)

    data['Wxx_hat'] = W_hat[0]
    data['Wxxu_hat'] = W_hat[1]
    data['Wxu_hat'] = W_hat[2]

    print(data['Wxx_hat'])
    print(data['Wxxu_hat'][0])
    print(data['Wxu_hat'])


    add_data_log(extra_prefix='final_')


plt.subplot(1, 2, 1)
plt.plot(data['x_true_merged'].data)
plt.plot(data['x_hat_merged'].data, '--')
plt.subplot(1, 2, 2)
plt.plot(data['y_true_merged'])
plt.plot(data['y_hat_merged'], '--')

'''
data_saved = {}
data_saved['non_smooth'] = data
RESULT_PATH_DCM_RNN = os.path.join(PROJECT_DIR, 'experiments', 'infer_x_from_y', 'equivalent_xs_part2.plk')
pickle.dump(data_saved, open(RESULT_PATH_DCM_RNN, 'wb'))
'''
