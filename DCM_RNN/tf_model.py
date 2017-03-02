# This module contains the tensorflow model for DCM-RNN.
import tensorflow as tf
import numpy as np

class DcmRnn:
    def __init__(self, n_recurrent_step=None,
                 variable_scope_name_x=None,
                 variable_scope_name_h=None):
        self.n_recurrent_step = n_recurrent_step or 12
        self.variable_scope_name_x = variable_scope_name_x or 'rnn_cell_x'
        self.variable_scope_name_h = variable_scope_name_h or 'rnn_cell_h'
        self.set_up_hyperparameter_values()

        self.trainable_flags_h = {'alpha': True,
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
        return deliverables

    def load_parameters(self, parameter_package):
        self.n_region = parameter_package['n_node']
        self.t_delta = parameter_package['t_delta']
        self.n_stimuli = parameter_package['n_stimuli']

    def set_up_hyperparameter_values(self):
        hyperparameter_values = {}
        hyperparameter_values[self.variable_scope_name_x] = {'gradient': 1., 'sparse': 1., 'prior': 0.}
        hyperparameter_values[self.variable_scope_name_h] = {'gradient': 1., 'sparse': 0., 'prior': 1.}
        self.hyperparameter_values = hyperparameter_values

    def create_shared_variables_h(self, initial_values):
        """
        Create shared hemodynamic variables.
        :param initial_values: a pandas.DataFrame, containing the initial values of hemodynamic variables
        :return:
        """
        n_region, n_para = initial_values.shape
        with tf.variable_scope(self.variable_scope_name_h):
            for idx_r, region_label in enumerate(list(initial_values.index)):
                for para in initial_values.columns:
                    tf.get_variable(para + '_r' + str(idx_r),
                                      initializer=initial_values[para][region_label],
                                      trainable=self.trainable_flags_h[para])

    def phi_h(self, h_state_current, alpha, E0):
        """
        Used to map hemodynamic states into higher dimension
        :param h_state_current:
        :param alpha:
        :param E0:
        :return:
        """
        # used to map hemodynamic states into higher dimension
        # for hemodynamic states evolvement
        h_state_augmented = []
        for i in range(4):
            h_state_augmented.append(h_state_current[i])
        h_state_augmented.append(tf.pow(h_state_current[2], tf.div(1., alpha)))
        h_state_augmented.append(tf.mul(tf.div(h_state_current[3], h_state_current[2]), h_state_augmented[4]))
        tmp = tf.sub(1., tf.pow(tf.sub(1., E0), tf.div(1., h_state_current[1])))
        tmp = tf.mul(tf.div(tmp, E0), h_state_current[1])
        h_state_augmented.append(tmp)
        return h_state_augmented

    def add_one_cell_h(self, h_state_current, x_state_current, i_region):
        """
        Model the evolving of hemodynamic states {s,f,v,q}
        This is independent for each region
        Here x_state_current is r scalar for r particular region
        :param h_state_current:
        :param x_state_current:
        :param i_region:
        :return:
        """
        with tf.variable_scope(self.variable_scope_name_h, reuse=True):
            alpha = tf.get_variable('alpha_r' + str(i_region))
            E0 = tf.get_variable('E0_r' + str(i_region))
            k = tf.get_variable('k_r' + str(i_region))
            gamma = tf.get_variable('gamma_r' + str(i_region))
            tao = tf.get_variable('tao_r' + str(i_region))
            x_h_coupling = tf.get_variable('x_h_coupling_r' + str(i_region))
            t_delta = self.t_delta

            h_state_augmented = self.phi_h(h_state_current, alpha, E0)
            h_state_next = []
            # s
            tmp1 = tf.mul(t_delta, x_state_current)
            tmp2 = tf.mul(tf.sub(tf.mul(t_delta, k), 1.), h_state_augmented[0])
            tmp3 = tf.mul(t_delta, tf.mul(gamma, tf.sub(h_state_augmented[1], 1.)))
            tmp = tf.sub(tmp1, tf.add(tmp2, tmp3))
            h_state_next.append(tf.reshape(tmp, [1, 1]))
            # f
            tmp = tf.add(h_state_augmented[1], tf.mul(t_delta, h_state_augmented[0]))
            h_state_next.append(tf.reshape(tmp, [1, 1]))
            # v
            tmp = t_delta * h_state_augmented[1] / tao \
                  - t_delta / tao * h_state_augmented[4] \
                  + h_state_augmented[2]
            h_state_next.append(tf.reshape(tmp, [1, 1]))
            # q
            tmp = h_state_augmented[3] \
                  + t_delta / tao * h_state_augmented[6] \
                  - t_delta / tao * h_state_augmented[5]
            h_state_next.append(tf.reshape(tmp, [1, 1]))
            # concantenate into a tensor
            h_state_next = tf.concat(0, h_state_next)
            h_state_next = tf.reshape(h_state_next, [4, 1])
            return h_state_next


    def build_an_initializer_graph(self, graph, parameter_package):
        """
        Build a model to estimate neural states from functional signal
        :param graph: a graph handle to draw tensorflow on
        :param parameter_package: a dictionary containing parameters needed
        :return: graph
        """
        # create variables


        pass