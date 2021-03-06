# This module contains the tensorflow model for DCM-RNN.
import tensorflow as tf
import numpy as np
from toolboxes import Initialization
import toolboxes as tb
import warnings
import pandas as pd
from collections import Iterable


# import pandas as pd
# from IPython.display import display


class DcmRnn(Initialization):
    def __init__(self,
                 n_recurrent_step=None,
                 learning_rate=None,
                 stop_threshold=None,

                 variable_scope_name_u_stacked=None,

                 variable_scope_name_x_parameter=None,
                 variable_scope_name_x_initial=None,
                 variable_scope_name_x=None,
                 variable_scope_name_x_tailing=None,
                 variable_scope_name_x_extended=None,
                 variable_scope_name_x_connector=None,
                 variable_scope_name_x_stacked=None,

                 variable_scope_name_h_parameter=None,
                 variable_scope_name_h_initial=None,
                 variable_scope_name_h_prelude=None,
                 variable_scope_name_h=None,
                 variable_scope_name_h_final=None,
                 variable_scope_name_h_stacked=None,

                 variable_scope_name_y=None,
                 variable_scope_name_y_stacked=None,
                 variable_scope_name_loss=None,
                 log_directory=None):
        Initialization.__init__(self)
        self.n_recurrent_step = n_recurrent_step or 12
        self.learning_rate = learning_rate or 0.01
        self.stop_threshold = stop_threshold or 1e-3
        self.shift_x_y = 3
        self.shift_u_y = 4
        self.shift_u_x = 1
        self.shift_data = int(self.n_recurrent_step / 2)
        self.if_add_optimiser = True  # turn off when do testing to save time

        self.variable_scope_name_u_stacked = variable_scope_name_u_stacked or 'u_stacked'
        self.variable_scope_name_u = variable_scope_name_x or 'cell_u'

        self.variable_scope_name_x_parameter = variable_scope_name_x_parameter or 'para_x'
        # self.variable_scope_name_x_initial = variable_scope_name_x_initial or 'cell_x_initial'
        self.variable_scope_name_x = variable_scope_name_x or 'cell_x'
        self.variable_scope_name_x_tailing = variable_scope_name_x_tailing or 'cell_x_tailing'
        # self.variable_scope_name_x_connector = variable_scope_name_x_connector or 'cell_x_connector'
        # self.variable_scope_name_x_extended = variable_scope_name_x_extended or 'cell_x_extended'
        self.variable_scope_name_x_stacked = variable_scope_name_x_stacked or 'x_stacked'

        self.variable_scope_name_h_parameter = variable_scope_name_h_parameter or 'para_h'
        self.variable_scope_name_h_initial = variable_scope_name_h_initial or 'cell_h_initial'
        # self.variable_scope_name_h_prelude = variable_scope_name_h_prelude or 'cell_h_prelude'
        self.variable_scope_name_h = variable_scope_name_h or 'cell_h'
        # self.variable_scope_name_h_connector = variable_scope_name_h_final or 'cell_h_connector'
        self.variable_scope_name_h_stacked = variable_scope_name_h_stacked or 'h_stacked'

        self.variable_scope_name_y = variable_scope_name_y or 'cell_y'
        self.variable_scope_name_y_stacked = variable_scope_name_y_stacked or 'y_stacked'

        self.variable_scope_name_loss = variable_scope_name_loss or 'loss'

        self.log_directory = log_directory or './logs'

        self.set_up_loss_weighting()
        self.trainable_flags = {'Wxx': True,
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

        self.batch_size = 128
        self.max_parameter_change_per_iteration = 0.001
        self.max_parameter_change_decreasing_rate = 0.9
        self.max_back_track_steps = 8

    def decrease_max_parameter_change_per_iteration(self, rate=None):
        """

        :param rate:
        :return:
        """
        if rate is None:
            rate = self.max_parameter_change_decreasing_rate
        self.max_parameter_change_per_iteration = self.max_parameter_change_per_iteration * rate

    def collect_parameters(self, du):
        """
        Collect needed parameters from a DataUnit instant.
        :param du: a DataUnit instant
        :return: a dictionary containing needed paramters
        """
        deliverables = {}
        needed_parameters = {'n_node', 'n_stimuli', 't_delta'}
        for para in needed_parameters:
            deliverables[para] = du.get(para)
        self.load_parameters(deliverables)
        return deliverables

    def load_parameters(self, parameter_package):
        self.n_region = parameter_package['n_node']
        self.t_delta = parameter_package['t_delta']
        self.n_stimuli = parameter_package['n_stimuli']

    def set_up_loss_weighting(self):
        self.loss_weighting = \
            {'prediction': 1., 'sparsity': 1., 'prior': 1., 'Wxx': 1., 'Wxxu': 1., 'Wxu': 1., 'smooth': 4.}

    def create_shared_variables_x(self, neural_parameter_initial):
        """
        Create shared tensorflow variables (connectivity) for neural evolution. 
        :param neural_parameter_initial: a list [A, [B's], C]
        :return: 
        """
        self.A = neural_parameter_initial['A']
        self.B = neural_parameter_initial['B']
        self.C = neural_parameter_initial['C']

        self.Wxx_init = np.array(self.A, dtype=np.float32) * self.t_delta + \
                        np.eye(self.n_region, self.n_region, 0, dtype=np.float32)
        self.Wxxu_init = [np.array(m, dtype=np.float32) * self.t_delta for m in self.B]
        self.Wxu_init = np.array(self.C, dtype=np.float32).reshape(self.n_region, self.n_stimuli) * self.t_delta

        with tf.variable_scope(self.variable_scope_name_x_parameter):
            self.Wxx = tf.get_variable(
                'Wxx', dtype=tf.float32, initializer=self.Wxx_init, trainable=self.trainable_flags['Wxx'])
            self.Wxxu = [tf.get_variable('Wxxu' + '_s' + str(n), dtype=tf.float32, initializer=self.Wxxu_init[n],
                                         trainable=self.trainable_flags['Wxxu'])
                         for n in range(self.n_stimuli)]
            self.Wxu = tf.get_variable('Wxu', dtype=tf.float32,
                                       initializer=self.Wxu_init, trainable=self.trainable_flags['Wxu'])
        self.x_parameters = [self.Wxx, self.Wxxu, self.Wxu]
        return self.x_parameters

    def create_shared_variables_h(self, initial_values):
        """
        Create shared tensorflow variables for hemodynamic proecess.
        :param initial_values: a pandas.DataFrame, containing the initial values of hemodynamic variables
        :return:
        """
        hemodynamic_parameter = []
        with tf.variable_scope(self.variable_scope_name_h_parameter):
            for idx_r, region_label in enumerate(list(initial_values.index)):
                temp_list = []
                for para in initial_values.columns:
                    temp = tf.get_variable(para + '_r' + str(idx_r),
                                           dtype=tf.float32,
                                           initializer=np.array(initial_values[para][region_label], dtype=np.float32),
                                           trainable=self.trainable_flags[para])
                    temp_list.append(temp)
                temp_tensor = tf.stack(temp_list, 0)
                hemodynamic_parameter.append(temp_tensor)
            hemodynamic_parameter = tf.stack(hemodynamic_parameter, 1, 'hemodynamic_parameter')
            hemodynamic_parameter = tf.transpose(hemodynamic_parameter)
        self.h_parameters = hemodynamic_parameter
        return self.h_parameters

    def phi_h(self, h_state_current, alpha, E0):
        """
        Used to map hemodynamic states into higher dimension
        :param h_state_current:
        :param alpha:
        :param E0:
        :return:
        """
        h_state_augmented = []
        for i in range(4):
            h_state_augmented.append(h_state_current[i])
        h_state_augmented.append(tf.pow(h_state_current[2], tf.div(1., alpha)))
        h_state_augmented.append(tf.multiply(tf.div(h_state_current[3], h_state_current[2]), h_state_augmented[4]))
        tmp = tf.subtract(1., tf.pow(tf.subtract(1., E0), tf.div(1., h_state_current[1])))
        tmp = tf.multiply(tf.div(tmp, E0), h_state_current[1])
        h_state_augmented.append(tmp)
        return h_state_augmented

    def phi_h_parallel(self, h_state_current, alpha, E0):
        """
        Used to map hemodynamic states into higher dimension
        :param h_state_current: [batch_size, 4]
        :param alpha:
        :param E0:
        :return: [batch_size, 7]
        """
        h_state_augmented = []
        for i in range(4):
            h_state_augmented.append(h_state_current[:, i])

        h_state_augmented.append(tf.pow(h_state_current[:, 2], tf.div(1., alpha)))

        h_state_augmented.append(tf.multiply(tf.div(h_state_current[:, 3], h_state_current[:, 2]),
                                             h_state_augmented[4]))

        tmp = tf.subtract(1., tf.pow(tf.subtract(1., E0), tf.div(1., h_state_current[:, 1])))
        tmp = tf.multiply(tf.div(tmp, E0), h_state_current[:, 1])
        h_state_augmented.append(tmp)

        h_state_augmented = tf.stack(h_state_augmented, axis=1)
        return h_state_augmented

    def get_h_para_tensor_for_one_region(self, i_region):
        """
        Get hemodynamic parameter tensors for a particular region
        :param i_region:
        :return: a dictionary
        """
        output = {}
        for para in self.hemo_parameter_keys:
            output[para] = tf.get_variable(para + '_r' + str(i_region))
        return output

    def add_one_cell_x(self, u_current, x_state_previous, x_parameter):
        """
        Model the evolving of neural activity x.
        :param u_current: 
        :param x_state_previous: 
        :return: 
        """
        n_stimuli = self.n_stimuli
        Wxx = x_parameter[0]
        Wxxu = x_parameter[1]
        Wxu = x_parameter[2]

        if x_state_previous.get_shape().ndims == 1:
            tmp1 = tf.matmul(Wxx, tf.expand_dims(x_state_previous, 1))
        else:
            tmp1 = tf.matmul(Wxx, x_state_previous)

        if x_state_previous.get_shape().ndims == 1:
            tmp2 = [tf.matmul(Wxxu[n] * u_current[n], tf.expand_dims(x_state_previous, 1)) for n in range(n_stimuli)]
        else:
            tmp2 = [tf.matmul(Wxxu[n] * u_current[n], x_state_previous) for n in range(n_stimuli)]
        tmp2 = tf.add_n(tmp2)
        # print(u_current.get_shape().ndims)
        if u_current.get_shape().ndims == 1:
            tmp3 = tf.matmul(Wxu, tf.expand_dims(u_current, 1))
        else:
            tmp3 = tf.matmul(Wxu, u_current)
        return tf.squeeze(tmp1 + tmp2 + tmp3)

    def add_one_cell_x_parallel(self, u_current, x_state_previous, x_parameter):
        """
        Model the evolving of neural activity x.
        :param u_current:
        :param x_state_previous:
        :return:
        """
        n_stimuli = self.n_stimuli
        Wxx = x_parameter[0]
        Wxxu = x_parameter[1]
        Wxu = x_parameter[2]

        temp_x = tf.reshape(tf.transpose(x_state_previous), [self.n_region, -1])
        temp_u = tf.reshape(tf.transpose(u_current), [self.n_stimuli, -1])

        temp1 = tf.reshape(tf.transpose(tf.matmul(Wxx, temp_x)), [self.batch_size, self.n_region])

        temp2 = [tf.reshape(tf.transpose(tf.matmul(Wxxu[n], temp_u[n, :] * temp_x)),
                            [self.batch_size, self.n_region]) for n in range(n_stimuli)]
        temp2 = tf.add_n(temp2)

        temp3 = tf.reshape(tf.transpose(tf.matmul(Wxu, temp_u)), [self.batch_size, self.n_region])

        return temp1 + temp2 + temp3

    def add_one_cell_h(self, h_state_current, x_state_current, h_parameter):
        """
        Model the evolving of hemodynamic states {s,f,v,q}
        This is independent for each region
        Here x_state_current is r scalar for r particular region
        :param h_state_current:
        :param x_state_current:
        :param h_parameter: a dictionary with all hemodynamic parameter
        :return:
        """
        # with tf.variable_scope(self.variable_scope_name_h, reuse=True):
        alpha = h_parameter["alpha"]
        k = h_parameter["k"]
        E0 = h_parameter["E0"]
        gamma = h_parameter["gamma"]
        tao = h_parameter["tao"]
        x_h_coupling = h_parameter["x_h_coupling"]
        t_delta = self.t_delta

        h_state_augmented = self.phi_h(h_state_current, alpha, E0)
        h_state_next = []
        # s
        tmp1 = tf.multiply(t_delta, x_h_coupling * tf.squeeze(x_state_current))
        tmp2 = tf.multiply(tf.subtract(tf.multiply(t_delta, k), 1.), h_state_augmented[0])
        tmp3 = tf.multiply(t_delta, tf.multiply(gamma, tf.subtract(h_state_augmented[1], 1.)))
        tmp = tf.subtract(tmp1, tf.add(tmp2, tmp3))
        h_state_next.append(tmp)
        # f
        tmp = tf.add(h_state_augmented[1], tf.multiply(t_delta, h_state_augmented[0]))
        h_state_next.append(tmp)
        # v
        tmp = t_delta * h_state_augmented[1] / tao \
              - t_delta / tao * h_state_augmented[4] \
              + h_state_augmented[2]
        h_state_next.append(tmp)
        # q
        tmp = h_state_augmented[3] \
              + t_delta / tao * h_state_augmented[6] \
              - t_delta / tao * h_state_augmented[5]
        h_state_next.append(tmp)
        # concantenate into a tensor
        h_state_next = tf.stack(h_state_next, 0)
        return h_state_next

    def add_one_cell_h_parallel(self, h_state_current, x_state_current, h_parameter):
        """
        Model the evolving of hemodynamic states {s,f,v,q} for one brain region
        This is independent for each region
        Here x_state_current is r scalar for r particular region
        :param h_state_current: [batch_size, 4]
        :param x_state_current: [batch_size]
        :param h_parameter: a dictionary with all hemodynamic parameter
        :return: [batch_size, 4]
        """
        # with tf.variable_scope(self.variable_scope_name_h, reuse=True):
        alpha = h_parameter["alpha"]
        k = h_parameter["k"]
        E0 = h_parameter["E0"]
        gamma = h_parameter["gamma"]
        tao = h_parameter["tao"]
        x_h_coupling = h_parameter["x_h_coupling"]
        t_delta = self.t_delta

        h_state_augmented = self.phi_h_parallel(h_state_current, alpha, E0)
        h_state_next = []
        # s
        tmp1 = tf.multiply(t_delta, x_h_coupling * x_state_current)
        tmp2 = tf.multiply(tf.subtract(tf.multiply(t_delta, k), 1.), h_state_augmented[:, 0])
        tmp3 = tf.multiply(t_delta, tf.multiply(gamma, tf.subtract(h_state_augmented[:, 1], 1.)))
        tmp = tf.subtract(tmp1, tf.add(tmp2, tmp3))
        h_state_next.append(tmp)
        # f
        tmp = tf.add(h_state_augmented[:, 1], tf.multiply(t_delta, h_state_augmented[:, 0]))
        h_state_next.append(tmp)
        # v
        tmp = t_delta * h_state_augmented[:, 1] / tao \
              - t_delta / tao * h_state_augmented[:,  4] \
              + h_state_augmented[:, 2]
        h_state_next.append(tmp)
        # q
        tmp = h_state_augmented[:, 3] \
              + t_delta / tao * h_state_augmented[:, 6] \
              - t_delta / tao * h_state_augmented[:, 5]
        h_state_next.append(tmp)
        # concantenate into a tensor

        h_state_next = tf.stack(h_state_next, 1)
        return h_state_next

    def add_neural_layer(self, u_extend, x_state_initial=None):
        """
        
        :param u_extend: input stimuli 
        :param x_state_initial: 
        :return: 
        """
        if x_state_initial is None:
            x_state_initial = self.x_state_initial
        n_stimuli = self.n_stimuli

        with tf.variable_scope(self.variable_scope_name_x_parameter, reuse=True):
            Wxx = tf.get_variable("Wxx")
            Wxxu = [tf.get_variable("Wxxu_s" + str(n)) for n in range(n_stimuli)]
            Wxu = tf.get_variable("Wxu")
        x_parameter = [Wxx, Wxxu, Wxu]

        # with tf.variable_scope(self.variable_scope_name_x):
        #     self.x_whole = [self.x_state_initial]
        for i in range(len(u_extend)):
            with tf.variable_scope(self.variable_scope_name_x):
                if i == 0:
                    self.x_whole = [self.x_state_initial]
                else:
                    self.x_whole.append(self.add_one_cell_x(u_extend[i - 1], self.x_whole[i - 1], x_parameter))

        # label x whole into different parts
        self.x_extended = self.x_whole[self.shift_u_x: self.shift_u_x + self.n_recurrent_step + self.shift_x_y]
        self.x_predicted = self.x_whole[self.shift_u_x: self.shift_u_x + self.n_recurrent_step]
        self.x_monitor = self.x_whole[:self.n_recurrent_step]
        self.x_connector = self.x_whole[self.shift_data]

        with tf.variable_scope(self.variable_scope_name_x_stacked):
            self.x_extended_stacked = tf.stack(self.x_extended, 0, name='x_extended_stacked')
            self.x_predicted_stacked = tf.stack(self.x_predicted, 0, name='x_predicted_stacked')
            self.x_monitor_stacked = tf.stack(self.x_monitor, 0, name='x_monitor_stacked')

    def add_neural_layer_parallel(self, u_extend, x_state_initial=None):
        """
        :param u_extend: input stimuli
        :param x_state_initial:
        :return:
        """
        if x_state_initial is None:
            x_state_initial = self.x_state_initial
        n_stimuli = self.n_stimuli

        with tf.variable_scope(self.variable_scope_name_x_parameter, reuse=True):
            Wxx = tf.get_variable("Wxx")
            Wxxu = [tf.get_variable("Wxxu_s" + str(n)) for n in range(n_stimuli)]
            Wxu = tf.get_variable("Wxu")
        x_parameter = [Wxx, Wxxu, Wxu]

        for i in range(len(u_extend)):
            with tf.variable_scope(self.variable_scope_name_x):
                if i == 0:
                    self.x_whole = [x_state_initial]
                else:
                    self.x_whole.append(self.add_one_cell_x_parallel(u_extend[i - 1], self.x_whole[i - 1], x_parameter))

        # label x whole into different parts
        self.x_extended = self.x_whole[self.shift_u_x: self.shift_u_x + self.n_recurrent_step + self.shift_x_y]
        self.x_predicted = self.x_whole[self.shift_u_x: self.shift_u_x + self.n_recurrent_step]
        self.x_monitor = self.x_whole[:self.n_recurrent_step]
        self.x_connector = self.x_whole[self.shift_data]

        with tf.variable_scope(self.variable_scope_name_x_stacked):
            self.x_extended_stacked = tf.stack(self.x_extended, 1, name='x_extended_stacked')
            self.x_predicted_stacked = tf.stack(self.x_predicted, 1, name='x_predicted_stacked')
            self.x_monitor_stacked = tf.stack(self.x_monitor, 1, name='x_monitor_stacked')

    def add_hemodynamic_layer(self, x_extended=None, h_state_initial=None):
        """
        Conceptually, hemodynamic layer consists of five parts:
        # format: h_initial_segment[region, 4]
        # format: h_prelude[self.shift_x_y][region, 4]
        # format: h_predicted[self.n_recurrent_step][region, 4]
        # format: h_connector[region, 4]
        # format: h_state_predicted_stacked[self.n_recurrent_step, region, 4]
        :param x_extended:
        :param h_state_initial:
        :return:
        """
        if x_extended is None:
            x_extended = self.x_extended
        if h_state_initial is None:
            h_state_initial = self.h_state_initial

        # calculate a large y layer with extended x state and then slicing to each parts
        for i in range(0, len(x_extended)):
            # load in shared parameters
            with tf.variable_scope(self.variable_scope_name_h_parameter, reuse=True):
                para_packages = []
                for i_region in range(self.n_region):
                    para_packages.append(self.get_h_para_tensor_for_one_region(i_region))
            # do evolving calculation
            with tf.variable_scope(self.variable_scope_name_h):
                if i == 0:
                    self.h_whole = [h_state_initial]
                else:
                    h_temp = []
                    for i_region in range(self.n_region):
                        h_temp.append(self.add_one_cell_h(
                            self.h_whole[i - 1][i_region, :], x_extended[i - 1][i_region],
                            para_packages[i_region]))
                    self.h_whole.append(tf.stack(h_temp, 0))

        # label h whole into different parts
        # self.h_prelude = self.h_whole[: self.shift_x_y]
        self.h_predicted = self.h_whole[self.shift_x_y: self.shift_x_y + self.n_recurrent_step]
        self.h_monitor = self.h_whole[:self.n_recurrent_step]
        self.h_connector = self.h_whole[self.shift_data]

        with tf.variable_scope(self.variable_scope_name_h_stacked):
            self.h_state_predicted_stacked = tf.stack(self.h_predicted, 0, name='h_predicted_stack')
            self.h_state_monitor_stacked = tf.stack(self.h_monitor, 0, name='h_monitor_stack')

    def add_hemodynamic_layer_parallel(self, x_extended=None, h_state_initial=None):
        """
        Conceptually, hemodynamic layer consists of five parts:
        # format: h_initial_segment[batch_size, 1, region, 4]
        # format: h_state_predicted_stacked[batch_size, self.n_recurrent_step, region, 4]
        :param x_extended:
        :param h_state_initial:
        :return:
        """
        if x_extended is None:
            x_extended = self.x_extended
        if h_state_initial is None:
            h_state_initial = self.h_state_initial

        # calculate a large h layer with extended x state and then slicing to each parts
        for i in range(0, len(x_extended)):
            # load in shared parameters
            with tf.variable_scope(self.variable_scope_name_h_parameter, reuse=True):
                para_packages = []
                for i_region in range(self.n_region):
                    para_packages.append(self.get_h_para_tensor_for_one_region(i_region))
            # do evolving calculation
            with tf.variable_scope(self.variable_scope_name_h):
                if i == 0:
                    self.h_whole = [h_state_initial]
                else:
                    h_temp = []
                    for i_region in range(self.n_region):
                        h_temp.append(self.add_one_cell_h_parallel(
                            self.h_whole[i - 1][:, i_region, :], x_extended[i - 1][:, i_region],
                            para_packages[i_region]))
                    self.h_whole.append(tf.stack(h_temp, 1))

        # label h whole into different parts
        # self.h_prelude = self.h_whole[: self.shift_x_y]
        self.h_predicted = self.h_whole[self.shift_x_y: self.shift_x_y + self.n_recurrent_step]
        self.h_monitor = self.h_whole[:self.n_recurrent_step]
        self.h_connector = self.h_whole[self.shift_data]

        with tf.variable_scope(self.variable_scope_name_h_stacked):
            self.h_state_predicted_stacked = tf.stack(self.h_predicted, 1, name='h_predicted_stack')
            self.h_state_monitor_stacked = tf.stack(self.h_monitor, 1, name='h_monitor_stack')

    def phi_o(self, h_state_current):
        """
        Used to map hemodynamic states into higher dimension to calculate fMRI signal
        :param h_state_current:
        :return:
        """
        o_state_augmented = [h_state_current[i + 2] for i in range(2)]
        tmp = tf.div(o_state_augmented[1], o_state_augmented[0])
        o_state_augmented.append(tmp)
        return o_state_augmented

    def phi_o_parallel(self, h_state_current):
        """
        Used to map hemodynamic states into higher dimension to calculate fMRI signal
        :param h_state_current: [batch_size, 4]
        :return:
        """
        o_state_augmented = [h_state_current[:, i + 2] for i in range(2)]
        tmp = tf.div(o_state_augmented[1], o_state_augmented[0])
        o_state_augmented.append(tmp)
        return o_state_augmented

    def output_mapping(self, h_state_current, parameter_package):

        E0 = parameter_package['E0']
        epsilon = parameter_package['epsilon']
        V0 = parameter_package['V0']
        TE = parameter_package['TE']
        r0 = parameter_package['r0']
        theta0 = parameter_package['theta0']

        k1 = 4.3 * theta0 * E0 * TE
        k2 = epsilon * r0 * E0 * TE
        k3 = 1 - epsilon

        o_state_augmented = self.phi_o(h_state_current)

        y = V0 * k1 * (1 - o_state_augmented[1]) \
            + V0 * k2 * (1 - o_state_augmented[2]) \
            + V0 * k3 * (1 - o_state_augmented[0])

        return y

    def output_mapping_parallel(self, h_state_current, parameter_package):

        E0 = parameter_package['E0']
        epsilon = parameter_package['epsilon']
        V0 = parameter_package['V0']
        TE = parameter_package['TE']
        r0 = parameter_package['r0']
        theta0 = parameter_package['theta0']

        k1 = 4.3 * theta0 * E0 * TE
        k2 = epsilon * r0 * E0 * TE
        k3 = 1 - epsilon

        o_state_augmented = self.phi_o_parallel(h_state_current)

        y = V0 * k1 * (1 - o_state_augmented[1]) \
            + V0 * k2 * (1 - o_state_augmented[2]) \
            + V0 * k3 * (1 - o_state_augmented[0])

        return y

    def add_output_layer(self, h_state_predicted=None):
        h_state_predicted = h_state_predicted or self.h_predicted
        self.y_predicted = []

        for i in range(0, self.n_recurrent_step):
            with tf.variable_scope(self.variable_scope_name_h_parameter, reuse=True):
                para_packages = []
                for i_region in range(self.n_region):
                    para_packages.append(self.get_h_para_tensor_for_one_region(i_region))
            with tf.variable_scope(self.variable_scope_name_y):
                y_temp = []
                for i_region in range(self.n_region):
                    y_temp.append(self.output_mapping(h_state_predicted[i][i_region, :], para_packages[i_region]))
                y_temp = tf.stack(y_temp, 0)
                self.y_predicted.append(y_temp)
        with tf.variable_scope(self.variable_scope_name_y_stacked):
            self.y_predicted_stacked = tf.stack(self.y_predicted, 0, name='y_predicted_stack')

    def add_output_layer_parallel(self, h_state_predicted=None):
        h_state_predicted = h_state_predicted or self.h_predicted
        self.y_predicted = []

        for i in range(0, self.n_recurrent_step):
            with tf.variable_scope(self.variable_scope_name_h_parameter, reuse=True):
                para_packages = []
                for i_region in range(self.n_region):
                    para_packages.append(self.get_h_para_tensor_for_one_region(i_region))
            with tf.variable_scope(self.variable_scope_name_y):
                y_temp = []
                for i_region in range(self.n_region):
                    y_temp.append(self.output_mapping_parallel(
                        h_state_predicted[i][:, i_region, :], para_packages[i_region]))
                y_temp = tf.stack(y_temp, 1)
                self.y_predicted.append(y_temp)
        with tf.variable_scope(self.variable_scope_name_y_stacked):
            self.y_predicted_stacked = tf.stack(self.y_predicted, 1, name='y_predicted_stack')


    def build_an_initializer_graph(self, hemodynamic_parameter_initial=None):
        """
        Build a model to estimate neural states from functional signal
        :return:
        """

        if hemodynamic_parameter_initial is None:
            self.hemodynamic_parameter_initial = \
                self.get_standard_hemodynamic_parameters(self.n_region).astype(np.float32)
        else:
            self.hemodynamic_parameter_initial = hemodynamic_parameter_initial
            # x layer state
        with tf.variable_scope(self.variable_scope_name_x_stacked):
            self.x_state_stacked = \
                tf.get_variable(name='x_state_stacked', dtype=tf.float32, shape=[self.n_recurrent_step, self.n_region])
            self.x_state_stacked_previous = \
                tf.get_variable(name='x_state_stacked_previous',
                                dtype=tf.float32, shape=[self.n_recurrent_step, self.n_region], trainable=False)
        self.x_state = []
        for n in range(self.n_recurrent_step):
            with tf.variable_scope(self.variable_scope_name_x):
                self.x_state.append(self.x_state_stacked[n, :])
        self.x_tailing = []
        for n in range(self.shift_x_y):
            with tf.variable_scope(self.variable_scope_name_x_tailing):
                self.x_tailing.append(tf.constant(np.zeros(self.n_region, dtype=np.float32),
                                                  dtype=np.float32,
                                                  name='x_tailing_' + str(n)))
        self.x_extended = self.x_state
        self.x_extended.extend(self.x_tailing)

        # y layer parameter
        self.create_shared_variables_h(self.hemodynamic_parameter_initial)  # name_scope inside
        # y layer state: initial(port in), and connector(port out)
        with tf.variable_scope(self.variable_scope_name_h_initial):
            # no matter how much shift_x_y is, we only need h_state of one time point as the connector
            self.h_state_initial_initial = \
                self.set_initial_hemodynamic_state_as_inactivated(n_node=self.n_region).astype(np.float32)
            self.h_state_initial = \
                tf.get_variable('h_initial_segment',
                                initializer=self.h_state_initial_initial,
                                trainable=False)

        # build model
        self.add_hemodynamic_layer(self.x_extended, self.h_state_initial)
        self.add_output_layer(self.h_predicted)

        # define loss_prediction
        self.y_true = tf.placeholder(dtype=tf.float32, shape=[self.n_recurrent_step, self.n_region], name="y_true")
        with tf.variable_scope(self.variable_scope_name_loss):
            self.loss_prediction = self.mse(self.y_true, self.y_predicted_stacked, "loss_prediction")

            x_state_stacked_backtracked = tf.concat(
                [self.x_state_stacked_previous[self.shift_data - 2: self.shift_data], self.x_state_stacked], axis=0)
            self.loss_smooth = self.mse(self.second_order_smooth(x_state_stacked_backtracked))

            # self.loss_smooth = self.mse(self.x_state_stacked[0:-1, :], self.x_state_stacked[1:, :])
            # self.loss_smooth = tf.reduce_mean(tf.abs(self.x_state_stacked[0:-1, :] - self.x_state_stacked[1:, :]))
            self.loss_combined = self.loss_prediction + self.loss_weighting['smooth'] * self.loss_smooth
        with tf.variable_scope('accumulate_' + self.variable_scope_name_loss):
            self.loss_total = tf.get_variable('loss_total', initializer=0., trainable=False)
            self.sum_loss = tf.assign_add(self.loss_total, self.loss_combined, name='accumulate_loss')
            self.clear_loss_total = tf.assign(self.loss_total, 0., name='clear_loss_total')

        # define optimiser
        # self.train = tf.train.AdamOptimizer(self.learning_rate).minimize(self.loss_combined)
        self.train = tf.train.GradientDescentOptimizer(self.learning_rate).minimize(self.loss_combined)

        # define summarizer
        self.variable_summaries(self.loss_total)
        self.merged_summary = tf.summary.merge_all()
        self.summary_writer = tf.summary.FileWriter(self.log_directory, tf.get_default_graph())

        return self

    def run_initializer_graph(self, sess, h_state_initial, data_x):
        """
        Run forward the initializer graph
        :param sess:
        :param h_state_initial:
        :param data_x: a list of neural activity signal segment
        :return: [y_hat, h_state_monitor]
        """
        h_state_monitor = []
        h_state_connector = []
        y_predicted = []
        h_state_initial_segment = h_state_initial
        for x_segment in data_x:
            h_state_connector.append(h_state_initial_segment)
            y_segment, h_segment, h_connector = \
                sess.run([self.y_predicted_stacked, self.h_state_monitor_stacked, self.h_connector],
                         feed_dict={self.x_state_stacked: x_segment, self.h_state_initial: h_state_initial_segment})
            h_state_initial_segment = h_connector
            h_state_monitor.append(h_segment)
            y_predicted.append(y_segment)
        return [y_predicted, h_state_monitor, h_state_connector]

    def check_parameter_consistency(self):
        pass

    def project_wxx(self, wxx_previous, wxx_current, MAX_TEST_STEPS=8):
        """
        In the optimization process, the neural connection Wxx, may run out of its domain of 
        definiton. The function projects them back to it back.
        :param wxx_previous: value of wxx before updating
        :param wxx_current: value of wxx after updating
        :return: 
        """
        # w, _ = np.linalg.eig(wxx_previous)
        # if max(w.real) > 1:
        #     raise ValueError('wxx_previous is not proper!')

        if np.isnan(wxx_current).any():
            warnings.warn("wxx_current contains NaN. wxx not updated!")
            wxx = wxx_previous
        else:

            wxx_delta = (wxx_current - wxx_previous) / MAX_TEST_STEPS
            for i in range(MAX_TEST_STEPS, -1, -1):
                wxx = wxx_previous + wxx_delta * i
                w, _ = np.linalg.eig(wxx)
                if max(w.real) > 1:
                    continue
                else:
                    break

            if i == 0:
                warnings.warn("wxx not updated!")
            if i < MAX_TEST_STEPS:
                print('wxx is projected')

        return [wxx, i < MAX_TEST_STEPS]

    def build_main_graph(self, neural_parameter_initial, hemodynamic_parameter_initial=None):
        """
        The main graph of dcm_rnn, used to infer effective connectivity given fMRI signal and stimuli.
        :param neural_parameter_initial:
        :param hemodynamic_parameter_initial:
        :return:
        """

        self.neural_parameter_initial = neural_parameter_initial
        if hemodynamic_parameter_initial is None:
            self.hemodynamic_parameter_initial = \
                self.get_standard_hemodynamic_parameters(self.n_region).astype(np.float32)
        else:
            self.hemodynamic_parameter_initial = hemodynamic_parameter_initial

        self.check_parameter_consistency()

        # input stimuli u
        with tf.variable_scope(self.variable_scope_name_u_stacked):
            self.u_placeholder = \
                tf.placeholder(dtype=tf.float32, shape=[self.n_recurrent_step, self.n_stimuli],
                               name='u_placeholder')
        self.u = []
        for n in range(self.n_recurrent_step):
            with tf.variable_scope(self.variable_scope_name_u):
                self.u.append(self.u_placeholder[n, :])
        self.u_tailing = []
        for n in range(self.shift_u_y):
            self.u_tailing.append(tf.constant(np.zeros(self.n_stimuli, dtype=np.float32),
                                              dtype=np.float32,
                                              name='u_tailing_' + str(n)))
        self.u_extended = self.u
        self.u_extended.extend(self.u_tailing)

        # x layer
        self.x_parameters = self.create_shared_variables_x(self.neural_parameter_initial)
        self.x_state_initial_default = \
            self.set_initial_neural_state_as_zeros(self.n_region).astype(np.float32)
        self.x_state_initial = tf.get_variable('x_initial', initializer=self.x_state_initial_default, trainable=False)
        self.add_neural_layer(self.u_extended, self.x_state_initial)

        # h layer
        self.h_parameters = self.create_shared_variables_h(self.hemodynamic_parameter_initial)
        with tf.variable_scope(self.variable_scope_name_h_initial):
            self.h_state_initial_initial = \
                self.set_initial_hemodynamic_state_as_inactivated(n_node=self.n_region).astype(np.float32)
            self.h_state_initial = \
                tf.get_variable('h_initial_segment',
                                initializer=self.h_state_initial_initial,
                                trainable=False)
        self.add_hemodynamic_layer(self.x_extended, self.h_state_initial)

        # output layer
        self.add_output_layer(self.h_predicted)

        # define loss and optimizer
        self.y_true = tf.placeholder(dtype=tf.float32, shape=[self.n_recurrent_step, self.n_region], name="y_true")
        with tf.variable_scope(self.variable_scope_name_loss):
            self.loss_prediction = self.mse(self.y_true, self.y_predicted_stacked, "loss_prediction")
            self.loss_sparsity = self.add_loss_sparsity()
            self.loss_prior = self.add_loss_prior(self.h_parameters)
            self.loss_total = tf.reduce_sum([self.loss_weighting['prediction'] * self.loss_prediction,
                                             self.loss_weighting['sparsity'] * self.loss_sparsity,
                                             self.loss_weighting['prior'] * self.loss_prior],
                                            name='loss_total')
        if self.if_add_optimiser:
            # self.train = tf.train.AdamOptimizer(self.learning_rate).minimize(self.loss_total)
            # self.train = tf.train.GradientDescentOptimizer(self.learning_rate).minimize(self.loss_total)


            self.opt = tf.train.GradientDescentOptimizer(self.learning_rate)
            self.grads_and_vars = self.opt.compute_gradients(self.loss_total, tf.trainable_variables())
            self.processed_grads_and_vars = self.grads_and_vars
            self.opt.apply_gradients(self.processed_grads_and_vars)

            # self.train = tf.train.AdagradOptimizer(self.learning_rate).minimize(self.loss_total)

            # define summarizer
            self.variable_summaries(self.loss_prediction)
            self.variable_summaries(self.loss_sparsity)
            self.variable_summaries(self.loss_prior)
            self.variable_summaries(self.loss_total)
            self.merged_summary = tf.summary.merge_all()
            self.summary_writer = tf.summary.FileWriter(self.log_directory, tf.get_default_graph())

    def setup_support_mask(self, masks):
        """
        Set up support mask for the trainable variable in the computation graph.
        If a value in any variable is not supported, it's not updated in the back propagation process.
        It's a trainable flag for within each variable than tf trainable flag which is for each variable wise.
        :param masks: a dict of matrice, keys can be variable names in graph or more natural variable in dcm_rnn model.
        :return:
        """
        # support mask should be written in variable name in the graph
        # assume variables are all fully supported
        self.support_in_graph = {v.name: np.ones([int(d) for d in v.get_shape()]) for v in tf.trainable_variables()}
        # merge input masks info
        for key, val in masks.items():
            if key in [v.name for v in tf.trainable_variables()]:
                self.support_in_graph[key] = val
            elif key in ['Wxx', 'Wxu']:
                #getattr(self, key).name in [v.name for v in tf.trainable_variables()]:
                self.support_in_graph[getattr(self, key).name] = val
            elif key == 'Wxxu':
                for i in range(len(val)):
                    self.support_in_graph[getattr(self, key)[i].name] = val[i]
            else:
                raise KeyError(str(key) + ' is not a proper key')
        return self.support_in_graph

    def _setup_support_mask(self, masks):
        """
        Set up support mask for the trainable variable in the computation graph.
        If a value in any variable is not supported, it's not updated in the back propagation process.
        It's a trainable flag for within each variable than tf trainable flag which is for each variable wise.
        :param masks: a dict of matrice, keys can be variable names in graph or more natural variable in dcm_rnn model.
        :return:
        """
        # support mask should be written in variable name in the graph
        # assume variables are all fully supported
        self.support_in_graph = {v.name: np.ones([int(d) for d in v.get_shape()]) for v in tf.trainable_variables()}

        # merge input masks info
        for key, val in masks.items():
            if key in [v.name for v in tf.trainable_variables()]:
                self.support_in_graph[key] = val
            elif getattr(self, key).name in [v.name for v in tf.trainable_variables()]:
                self.support_in_graph[getattr(self, key).name] = val
            else:
                raise KeyError(str(key) + ' is not a proper key')
        return self.support_in_graph

    def update_variables_in_graph(self, sess, variable_names, variable_values):
        if isinstance(variable_names, str):
            sess.run(tf.assign(variable_names, variable_values))
        elif isinstance(variable_names, Iterable):
            assert len(variable_names) == len(variable_values)
            assign_ops = []
            for key, val in zip(variable_names, variable_values):
                assign_ops.append(tf.assign(key, val))
            sess.run(assign_ops)

    def add_loss_sparsity(self, loss_weighting=None):
        if loss_weighting == None:
            loss_weighting = self.loss_weighting
        '''
        loss_Wxx = tf.reduce_sum(tf.reshape(tf.abs(self.Wxx - np.identity(self.n_region, dtype=np.float32)), [-1]))
        loss_Wxxu = tf.reduce_sum(
            [tf.reduce_sum(tf.reshape(tf.abs(self.Wxxu[s]), [-1])) for s in range(self.n_stimuli)])
        loss_Wxu = tf.reduce_sum(tf.reshape(tf.abs(self.Wxu), [-1]))
        self.loss_sparsity = tf.reduce_sum([loss_weighting['Wxx'] * loss_Wxx, loss_weighting['Wxxu'] * loss_Wxxu,
                                            loss_weighting['Wxu'] * loss_Wxu], name="loss_sparsity")
        '''
        loss_Wxx = \
            loss_weighting['Wxx'] * tf.reshape(tf.abs(self.Wxx - np.identity(self.n_region, dtype=np.float32)), [-1])
        loss_Wxxu = tf.concat([loss_weighting['Wxxu'] * tf.reshape(tf.abs(self.Wxxu[s]), [-1])
                               for s in range(self.n_stimuli)], axis=0)
        loss_Wxu = loss_weighting['Wxu'] * tf.reshape(tf.abs(self.Wxu), [-1])
        self.loss_sparsity_Wxx = tf.reduce_sum(loss_Wxx)
        self.loss_sparsity_Wxxu = tf.reduce_sum(loss_Wxxu)
        self.loss_sparsity_Wxu = tf.reduce_sum(loss_Wxu)
        self.loss_sparsity = tf.reduce_mean(tf.concat([loss_Wxx, loss_Wxxu, loss_Wxu], axis=0), name="loss_sparsity")
        return self.loss_sparsity

    def add_loss_prior(self, h_parameters=None, loss_weighting=None):
        if h_parameters == None:
            h_parameters = self.h_parameters
        if loss_weighting == None:
            loss_weighting = self.loss_weighting
        prior_distribution = self.get_expanded_hemodynamic_parameter_prior_distributions(self.n_region)
        mask = np.array(prior_distribution['std'] > 0)
        mean = np.array(prior_distribution['mean'], dtype=np.float32)[mask]
        std = np.array(prior_distribution['std'], dtype=np.float32)[mask]
        temp = tf.square(tf.reshape(tf.boolean_mask(h_parameters, mask), [-1]) - mean) / tf.square(std)
        self.loss_prior = tf.reduce_mean(temp, name="loss_prior")
        return self.loss_prior

    def update_h_parameters_in_graph(self, sess, h_parameters_updated):
        """
        :param sess: 
        :param h_parameters_updated: a 2d matrix of size( n_region, n_h_parameters)
        :return:
        """
        sess.run(tf.assign(self.h_parameters, h_parameters_updated))

    def build_main_graph_parallel(self, neural_parameter_initial, hemodynamic_parameter_initial=None):
        """
        The main graph of dcm_rnn, used to infer effective connectivity given fMRI signal and stimuli.
        Trainable variables are updated after collecting gradients from all segments.
        In each segment, x, and h connectors are pre-calculated, so that gradient of each segment can be calculated
        independently, feed in as a batch.s
        :param neural_parameter_initial:
        :param hemodynamic_parameter_initial:
        :return:
        """

        self.neural_parameter_initial = neural_parameter_initial
        if hemodynamic_parameter_initial is None:
            self.hemodynamic_parameter_initial = \
                self.get_standard_hemodynamic_parameters(self.n_region).astype(np.float32)
        else:
            self.hemodynamic_parameter_initial = hemodynamic_parameter_initial

        self.check_parameter_consistency()

        # input stimuli u
        with tf.variable_scope(self.variable_scope_name_u_stacked):
            self.u_placeholder = \
                tf.placeholder(dtype=tf.float32, shape=[self.batch_size, self.n_recurrent_step, self.n_stimuli],
                               name='u_placeholder')
        self.u = []
        for n in range(self.n_recurrent_step):
            with tf.variable_scope(self.variable_scope_name_u):
                self.u.append(self.u_placeholder[:, n, :])
        self.u_tailing = []
        for n in range(self.shift_u_y):
            self.u_tailing.append(tf.constant(np.zeros((self.batch_size, 1, self.n_stimuli), dtype=np.float32),
                                              dtype=np.float32,
                                              name='u_tailing_' + str(n)))
        self.u_extended = self.u
        self.u_extended.extend(self.u_tailing)

        # x layer
        self.x_parameters = self.create_shared_variables_x(self.neural_parameter_initial)
        x_state_initial = np.tile(self.set_initial_neural_state_as_zeros(self.n_region).astype(np.float32),
                                  (self.batch_size, 1))
        self.x_state_initial = tf.get_variable('x_initial', initializer=x_state_initial, trainable=False)
        self.add_neural_layer_parallel(self.u_extended, self.x_state_initial)

        # h layer
        self.h_parameters = self.create_shared_variables_h(self.hemodynamic_parameter_initial)
        with tf.variable_scope(self.variable_scope_name_h_initial):
            h_state_initial = \
                self.set_initial_hemodynamic_state_as_inactivated(n_node=self.n_region).astype(np.float32)
            h_state_initial = np.expand_dims(h_state_initial, 0)
            h_state_initial = np.tile(h_state_initial, (self.batch_size, 1, 1))
            self.h_state_initial = \
                tf.get_variable('h_initial_segment',
                                initializer=h_state_initial,
                                trainable=False)
        self.add_hemodynamic_layer_parallel(self.x_extended, self.h_state_initial)

        # output layer
        self.add_output_layer_parallel(self.h_predicted)


        # define loss and optimizer
        self.y_true = tf.placeholder(dtype=tf.float32, shape=[self.batch_size, self.n_recurrent_step, self.n_region],
                                     name="y_true")
        with tf.variable_scope(self.variable_scope_name_loss):
            self.loss_prediction = self.mse(self.y_true, self.y_predicted_stacked, "loss_prediction")
            self.loss_sparsity = self.add_loss_sparsity()
            self.loss_prior = self.add_loss_prior(self.h_parameters)
            self.loss_total = tf.reduce_sum([self.loss_weighting['prediction'] * self.loss_prediction,
                                             self.loss_weighting['sparsity'] * self.loss_sparsity,
                                             self.loss_weighting['prior'] * self.loss_prior],
                                            name='loss_total')


        if self.if_add_optimiser:
            # self.train = tf.train.AdamOptimizer(self.learning_rate).minimize(self.loss_total)
            # self.train = tf.train.GradientDescentOptimizer(self.learning_rate).minimize(self.loss_total)


            self.opt = tf.train.GradientDescentOptimizer(self.learning_rate)
            self.grads_and_vars = self.opt.compute_gradients(self.loss_total, tf.trainable_variables())
            self.processed_grads_and_vars = self.grads_and_vars
            self.opt.apply_gradients(self.processed_grads_and_vars)

            # define summarizer
            self.variable_summaries(self.loss_prediction)
            self.variable_summaries(self.loss_sparsity)
            self.variable_summaries(self.loss_prior)
            self.variable_summaries(self.loss_total)
            self.merged_summary = tf.summary.merge_all()
            self.summary_writer = tf.summary.FileWriter(self.log_directory, tf.get_default_graph())


    # unitilies
    def mse(self, tensor1, tensor2=0., name=None):
        with tf.variable_scope('MSE'):
            mse = tf.reduce_mean((tf.reshape(tensor1, [-1]) - tf.reshape(tensor2, [-1])) ** 2)
            # mse = temp / self.get_element_count(tensor1)
            if name is not None:
                tf.identity(mse, name=name)
            return mse

    def second_order_smooth(self, tensor, axis=0):
        """
        Calculate the first order and second order derivative for smoothing
        :param tensor: 
        :param axis: smoothing direction, 0 or 1
        :return: 
        """
        signal_length = tensor.get_shape().as_list()[axis]

        # build operator matrices
        first_order_difference_operator = np.diag([1] * signal_length) + np.diag([-1] * (signal_length - 1), 1)
        second_order_difference_operator = np.diag([-2] * signal_length) \
                                           + np.diag([1] * (signal_length - 1), -1) \
                                           + np.diag([1] * (signal_length - 1), 1)
        first_order_difference_operator[-1] = 0
        second_order_difference_operator[0] = 0
        second_order_difference_operator[-1] = 0
        first_order_difference_operator = first_order_difference_operator.astype(np.float32)
        second_order_difference_operator = second_order_difference_operator.astype(np.float32)

        if axis == 0:
            first_order_difference = tf.matmul(first_order_difference_operator, tensor)
            second_order_difference = tf.matmul(second_order_difference_operator, tensor)
            derivative = tf.concat([first_order_difference, second_order_difference], axis=1)
        else:
            first_order_difference = tf.matmul(tensor, first_order_difference_operator)
            second_order_difference = tf.matmul(tensor, first_order_difference_operator)
            derivative = tf.concat([first_order_difference, second_order_difference], axis=0)

        return derivative

    def variable_summaries(self, tensor):
        """Attach a lot of summaries to a Tensor (for TensorBoard visualization)."""
        scope_name = 'Summary_' + tensor.op.name
        with tf.name_scope(scope_name):
            mean = tf.reduce_mean(tensor)
            tf.summary.scalar('mean', mean)
            with tf.name_scope('stddev'):
                stddev = tf.sqrt(tf.reduce_mean(tf.square(tensor - mean)))
            tf.summary.scalar('stddev', stddev)
            tf.summary.scalar('max', tf.reduce_max(tensor))
            tf.summary.scalar('min', tf.reduce_min(tensor))
            tf.summary.histogram('histogram', tensor)

    def show_all_variable_value(self, isess, visFlag=False):
        output = []
        output_buff = pd.DataFrame()
        parameter_key_list = [var.name for var in tf.get_collection(tf.GraphKeys.TRAINABLE_VARIABLES)]

        for idx, key in enumerate(self.parameter_key_list):
            if key == 'Wxx':
                values = isess.run(self.Wxx)
                tmp = pd.DataFrame(values, index=['To_r' + str(i) for i in range(self.n_region)], \
                                   columns=['From_r' + str(i) for i in range(self.n_region)])
                tmp.name = key
                output.append(tmp)
            elif key == 'Wxxu':
                values = isess.run(self.Wxxu)
                for n in range(self.n_stimuli):
                    tmp = pd.DataFrame(values[n], index=['To_r' + str(i) for i in range(self.n_region)], \
                                       columns=['From_r' + str(i) for i in range(self.n_region)])
                    tmp.name = key + '_s' + str(n)
                    output.append(tmp)
            elif key == 'Wxu':
                values = isess.run(self.Wxu)
                tmp = pd.DataFrame(values, index=['To_r' + str(i) for i in range(self.n_region)], \
                                   columns=['stimuli_' + str(i) for i in range(self.n_stimuli)])
                tmp.name = key
                output.append(tmp)
            else:
                values = eval('isess.run2(self.' + key + ')')
                # print(key)
                # print(true_values)
                tmp = [values[key + '_r' + str(i)] for i in range(self.n_region)]
                tmp = pd.Series(tmp, index=['region_' + str(i) for i in range(self.n_region)])
                output_buff[key] = tmp
        output_buff.name = 'hemodynamic_parameters'
        output.append(output_buff)
        if visFlag:
            for item in output:
                print(item.name)
                print(item)
        return output
