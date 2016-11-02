'''
### This script is used to check BP for DCM-RNN
- Keep the majority parameters "correct".
- Calculate the loss as a function of remaining parameter.
- Check whether BP can find the targeted optimal point.
'''

import importlib
import numpy as np
import scipy as sp
import tensorflow as tf
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib.mlab as mlab
from mpl_toolkits.mplot3d import axes3d
import math as mth
from tensorflow.python.framework import ops
from IPython.display import clear_output
from scipy.interpolate import interp1d
import os,shutil
import pandas as pd
from tensorflow.python.client import timeline

import CBI
import population
importlib.reload(CBI)
importlib.reload(population)

# Create a subject
flags = type('container', (object,), {})()
flags.random_hemodynamic_parameter = False
flags.random_h_state_initial = False
flags.random_x_state_initial = False

s=population.get_a_subject(flags=flags)
m=CBI.configure_a_scanner(t_delta=0.25,n_stimuli=1)
u,y,x,h=m.quick_scan(s,return_x=True,return_h=True)
parameter_true=s.show_all_variable_value(False)
plt.subplot(211)
plt.plot(np.arange(m.n_time_point)*m.t_delta,u.transpose())
plt.xlabel('time (s)')
plt.ylabel('stimuli')
plt.subplot(212)
plt.plot(np.arange(m.n_time_point)*m.t_delta,y[:,0,:].transpose())
plt.xlabel('time (s)')
plt.ylabel('fMRI signal')

print('This is the end of check_loss_and_BP.py')
