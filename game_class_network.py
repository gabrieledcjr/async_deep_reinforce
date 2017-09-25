# -*- coding: utf-8 -*-
import tensorflow as tf
import numpy as np

from abc import ABC, abstractmethod
from termcolor import colored

# Base Class
class GameClassNetwork(ABC):
  use_mnih_2015 = False
  l1_beta = 0. #NOT USED
  l2_beta = 0. #0.0001
  def __init__(self,
               action_size,
               thread_index, # -1 for global
               device="/cpu:0"):
    self._action_size = action_size
    self._thread_index = thread_index
    self._device = device

  @abstractmethod
  def prepare_loss(self):
    raise NotImplementedError()

  @abstractmethod
  def prepare_evaluate(self):
    raise NotImplementedError()

  @abstractmethod
  def load(self, sess, checkpoint):
    raise NotImplementedError()

  @abstractmethod
  def run_policy_and_value(self, sess, s_t):
    raise NotImplementedError()

  @abstractmethod
  def run_policy(self, sess, s_t):
    raise NotImplementedError()

  @abstractmethod
  def run_value(self, sess, s_t):
    raise NotImplementedError()

  @abstractmethod
  def get_vars(self):
    raise NotImplementedError()

  def sync_from(self, src_netowrk, name=None):
    src_vars = src_netowrk.get_vars()
    dst_vars = self.get_vars()

    sync_ops = []

    with tf.device(self._device):
      with tf.name_scope(name, "GameACNetwork", []) as name:
        for(src_var, dst_var) in zip(src_vars, dst_vars):
          sync_op = tf.assign(dst_var, src_var)
          sync_ops.append(sync_op)

        return tf.group(*sync_ops, name=name)

  # weight initialization based on muupan's code
  # https://github.com/muupan/async-rl/blob/master/a3c_ale.py
  def _fc_variable(self, weight_shape, layer_name=''):
    input_channels  = weight_shape[0]
    output_channels = weight_shape[1]
    d = 1.0 / np.sqrt(input_channels)
    bias_shape = [output_channels]
    weight = tf.Variable(tf.random_uniform(weight_shape, minval=-d, maxval=d), name=layer_name + '_weights')
    bias   = tf.Variable(tf.random_uniform(bias_shape,   minval=-d, maxval=d), name=layer_name + '_biases')
    return weight, bias

  def _conv_variable(self, weight_shape, layer_name=''):
    w = weight_shape[0]
    h = weight_shape[1]
    input_channels  = weight_shape[2]
    output_channels = weight_shape[3]
    d = 1.0 / np.sqrt(input_channels * w * h)
    bias_shape = [output_channels]
    weight = tf.Variable(tf.random_uniform(weight_shape, minval=-d, maxval=d), name=layer_name + '_weights')
    bias   = tf.Variable(tf.random_uniform(bias_shape,   minval=-d, maxval=d), name=layer_name + '_biases')
    return weight, bias

  def _conv2d(self, x, W, stride):
    return tf.nn.conv2d(x, W, strides = [1, stride, stride, 1], padding = "VALID")

# Multi-Classification Network
class MultiClassNetwork(GameClassNetwork):
  def __init__(self,
               action_size,
               thread_index, # -1 for global
               device="/cpu:0"):
    GameClassNetwork.__init__(self, action_size, thread_index, device)
    self.graph = tf.Graph()
    print (colored("action_size: {}".format(self._action_size), "green"))
    print (colored("use_mnih_2015: {}".format(self.use_mnih_2015), "green" if self.use_mnih_2015 else "red"))
    print (colored("L1_beta: {}".format(self.l1_beta), "green" if self.l1_beta > 0. else "red"))
    print (colored("L2_beta: {}".format(self.l2_beta), "green" if self.l2_beta > 0. else "red"))
    scope_name = "net_" + str(self._thread_index)
    with self.graph.as_default():
      with tf.device(self._device), tf.variable_scope(scope_name) as scope:
        if self.use_mnih_2015:
          self.W_conv1, self.b_conv1 = self._conv_variable([8, 8, 4, 32], layer_name='conv1')
          self.W_conv2, self.b_conv2 = self._conv_variable([4, 4, 32, 64], layer_name='conv2')
          self.W_conv3, self.b_conv3 = self._conv_variable([3, 3, 64, 64], layer_name='conv3')
          self.W_fc1, self.b_fc1 = self._fc_variable([3136, 256], layer_name='fc1')
          tf.add_to_collection('transfer_params', self.W_conv1)
          tf.add_to_collection('transfer_params', self.b_conv1)
          tf.add_to_collection('transfer_params', self.W_conv2)
          tf.add_to_collection('transfer_params', self.b_conv2)
          tf.add_to_collection('transfer_params', self.W_conv3)
          tf.add_to_collection('transfer_params', self.b_conv3)
          tf.add_to_collection('transfer_params', self.W_fc1)
          tf.add_to_collection('transfer_params', self.b_fc1)
        else:
          self.W_conv1, self.b_conv1 = self._conv_variable([8, 8, 4, 16], layer_name='conv1')  # stride=4
          self.W_conv2, self.b_conv2 = self._conv_variable([4, 4, 16, 32], layer_name='conv2') # stride=2
          self.W_fc1, self.b_fc1 = self._fc_variable([2592, 256], layer_name='fc1')
          tf.add_to_collection('transfer_params', self.W_conv1)
          tf.add_to_collection('transfer_params', self.b_conv1)
          tf.add_to_collection('transfer_params', self.W_conv2)
          tf.add_to_collection('transfer_params', self.b_conv2)
          tf.add_to_collection('transfer_params', self.W_fc1)
          tf.add_to_collection('transfer_params', self.b_fc1)

        # weight for policy output layer
        self.W_fc2, self.b_fc2 = self._fc_variable([256, action_size], layer_name='fc2')
        tf.add_to_collection('transfer_params', self.W_fc2)
        tf.add_to_collection('transfer_params', self.b_fc2)

        # state (input)
        self.s = tf.placeholder("float", [None, 84, 84, 4])

        if self.use_mnih_2015:
          h_conv1 = tf.nn.relu(self._conv2d(self.s,  self.W_conv1, 4) + self.b_conv1)
          h_conv2 = tf.nn.relu(self._conv2d(h_conv1, self.W_conv2, 2) + self.b_conv2)
          h_conv3 = tf.nn.relu(self._conv2d(h_conv2, self.W_conv3, 1) + self.b_conv3)

          h_conv3_flat = tf.reshape(h_conv3, [-1, 3136])
          h_fc1 = tf.nn.relu(tf.matmul(h_conv3_flat, self.W_fc1) + self.b_fc1)
        else:
          h_conv1 = tf.nn.relu(self._conv2d(self.s,  self.W_conv1, 4) + self.b_conv1)
          h_conv2 = tf.nn.relu(self._conv2d(h_conv1, self.W_conv2, 2) + self.b_conv2)

          h_conv2_flat = tf.reshape(h_conv2, [-1, 2592])
          h_fc1 = tf.nn.relu(tf.matmul(h_conv2_flat, self.W_fc1) + self.b_fc1)

        # policy (output)
        self._pi = tf.matmul(h_fc1, self.W_fc2) + self.b_fc2
        self.pi = tf.nn.softmax(self._pi)

        self.max_value = tf.reduce_max(self._pi, axis=None)
        self.saver = tf.train.Saver()

  def prepare_loss(self, class_weights=None):
    with self.graph.as_default():
      with tf.device(self._device):
        # taken action (input for policy)
        self.a = tf.placeholder(tf.float32, shape=[None, self._action_size])

        if class_weights is not None:
          # http://tf-unet.readthedocs.io/en/latest/_modules/tf_unet/unet.html
          class_weights = tf.constant(np.array(class_weights, dtype=np.float32))
          weight_map = tf.multiply(self.a, class_weights)
          weight_map = tf.reduce_sum(weight_map, axis=1)
          loss_map = tf.nn.softmax_cross_entropy_with_logits(
            _sentinel=None,
            labels=self.a,
            logits=self._pi)
          weighted_loss = tf.multiply(loss_map, weight_map)
          loss = weighted_loss
        else:
          loss = tf.nn.softmax_cross_entropy_with_logits(
            _sentinel=None,
            labels=self.a,
            logits=self._pi)

        net_vars = self.get_vars()
        l2_losses = []
        l1_losses = []
        for i in range(len(net_vars)):
          if i%2 == 0:
            # https://github.com/tensorflow/models/blob/master/inception/inception/slim/losses.py
            l1_losses.append(self.l1_beta * tf.reduce_sum(tf.abs(net_vars[i])))
            l2_losses.append(self.l2_beta * tf.nn.l2_loss(net_vars[i]))
        l1_loss = sum(l1_losses)
        l2_loss = sum(l2_losses)

        self.total_loss = tf.reduce_mean(loss + l1_loss + l2_loss)

  def run_policy_and_value(self, sess, s_t):
    raise NotImplementedError()

  def run_policy(self, sess, s_t):
    pi_out = sess.run( self.pi, feed_dict = {self.s : [s_t]} )
    return pi_out[0]

  def run_value(self, sess, s_t):
    raise NotImplementedError()

  def get_vars(self):
    if self.use_mnih_2015:
      return [self.W_conv1, self.b_conv1,
              self.W_conv2, self.b_conv2,
              self.W_conv3, self.b_conv3,
              self.W_fc1, self.b_fc1,
              self.W_fc2, self.b_fc2]
    else:
      return [self.W_conv1, self.b_conv1,
              self.W_conv2, self.b_conv2,
              self.W_fc1, self.b_fc1,
              self.W_fc2, self.b_fc2]

  def load(self, sess=None, checkpoint=''):
    assert sess != None
    assert checkpoint != ''
    self.saver.restore(sess, checkpoint)
    print (colored("Successfully loaded: {}".format(checkpoint), "green"))

  def prepare_evaluate(self):
    with self.graph.as_default():
      with tf.device(self._device):
        correct_prediction = tf.equal(tf.argmax(self._pi, 1), tf.argmax(self.a, 1))
        self.accuracy = tf.reduce_mean(tf.cast(correct_prediction, tf.float32))


# MTL Binary Classification Network
class MTLBinaryClassNetwork(GameClassNetwork):
  def __init__(self,
               action_size,
               thread_index, # -1 for global
               device="/cpu:0"):
    GameClassNetwork.__init__(self, action_size, thread_index, device)
    self.graph = tf.Graph()
    print (colored("action_size: {}".format(self._action_size), "green"))
    print (colored("use_mnih_2015: {}".format(self.use_mnih_2015), "green" if self.use_mnih_2015 else "red"))
    print (colored("L1_beta: {}".format(self.l1_beta), "green" if self.l1_beta > 0. else "red"))
    print (colored("L2_beta: {}".format(self.l2_beta), "green" if self.l2_beta > 0. else "red"))
    scope_name = "net_" + str(self._thread_index)
    with self.graph.as_default():
      with tf.device(self._device), tf.variable_scope(scope_name) as scope:
        if self.use_mnih_2015:
          self.W_conv1, self.b_conv1 = self._conv_variable([8, 8, 4, 32], layer_name='conv1')
          self.W_conv2, self.b_conv2 = self._conv_variable([4, 4, 32, 64], layer_name='conv2')
          self.W_conv3, self.b_conv3 = self._conv_variable([3, 3, 64, 64], layer_name='conv3')
          self.W_fc1, self.b_fc1 = self._fc_variable([3136, 256], layer_name='fc1')
          tf.add_to_collection('transfer_params', self.W_conv1)
          tf.add_to_collection('transfer_params', self.b_conv1)
          tf.add_to_collection('transfer_params', self.W_conv2)
          tf.add_to_collection('transfer_params', self.b_conv2)
          tf.add_to_collection('transfer_params', self.W_conv3)
          tf.add_to_collection('transfer_params', self.b_conv3)
          tf.add_to_collection('transfer_params', self.W_fc1)
          tf.add_to_collection('transfer_params', self.b_fc1)
        else:
          self.W_conv1, self.b_conv1 = self._conv_variable([8, 8, 4, 16], layer_name='conv1')  # stride=4
          self.W_conv2, self.b_conv2 = self._conv_variable([4, 4, 16, 32], layer_name='conv2') # stride=2
          self.W_fc1, self.b_fc1 = self._fc_variable([2592, 256], layer_name='fc1')
          tf.add_to_collection('transfer_params', self.W_conv1)
          tf.add_to_collection('transfer_params', self.b_conv1)
          tf.add_to_collection('transfer_params', self.W_conv2)
          tf.add_to_collection('transfer_params', self.b_conv2)
          tf.add_to_collection('transfer_params', self.W_fc1)
          tf.add_to_collection('transfer_params', self.b_fc1)

        # weight for policy output layer
        self.W_fc2, self.b_fc2 = [], []
        for n_class in range(action_size):
          W, b = self._fc_variable([256, 2], layer_name='fc2_{}'.format(n_class))
          self.W_fc2.append(W)
          self.b_fc2.append(b)
          tf.add_to_collection('transfer_params', self.W_fc2[n_class])
          tf.add_to_collection('transfer_params', self.b_fc2[n_class])

        # state (input)
        self.s = tf.placeholder("float", [None, 84, 84, 4])

        if self.use_mnih_2015:
          h_conv1 = tf.nn.relu(self._conv2d(self.s,  self.W_conv1, 4) + self.b_conv1)
          h_conv2 = tf.nn.relu(self._conv2d(h_conv1, self.W_conv2, 2) + self.b_conv2)
          h_conv3 = tf.nn.relu(self._conv2d(h_conv2, self.W_conv3, 1) + self.b_conv3)

          h_conv3_flat = tf.reshape(h_conv3, [-1, 3136])
          h_fc1 = tf.nn.relu(tf.matmul(h_conv3_flat, self.W_fc1) + self.b_fc1)
        else:
          h_conv1 = tf.nn.relu(self._conv2d(self.s,  self.W_conv1, 4) + self.b_conv1)
          h_conv2 = tf.nn.relu(self._conv2d(h_conv1, self.W_conv2, 2) + self.b_conv2)

          h_conv2_flat = tf.reshape(h_conv2, [-1, 2592])
          h_fc1 = tf.nn.relu(tf.matmul(h_conv2_flat, self.W_fc1) + self.b_fc1)

        # policy (output)
        self._pi, self.pi = [], []
        self.max_value = []
        for n_class in range(action_size):
          _pi = tf.matmul(h_fc1, self.W_fc2[n_class]) + self.b_fc2[n_class]
          self._pi.append(_pi)
          pi = tf.nn.softmax(self._pi[n_class])
          self.pi.append(pi)
          max_value = tf.reduce_max(self._pi[n_class], axis=None)
          self.max_value.append(max_value)

        self.saver = tf.train.Saver()

  def prepare_loss(self, class_weights=None, mtl=True):
    with self.graph.as_default():
      with tf.device(self._device):
        # taken action (input for policy)
        if mtl:
          self.a = tf.placeholder(tf.float32, shape=[None, 2])
        else:
          self.a = tf.placeholder(tf.float32, shape=[None, self._action_size])

        #net_vars = self.get_vars()
        #self.total_loss = tf.reduce_mean(loss + l1_loss + l2_loss)

        self.total_loss = []
        for n_class in range(self._action_size):
          #loss = tf.nn.l2_loss(self.a - self.pi[n_class])
          loss = tf.nn.softmax_cross_entropy_with_logits(
            _sentinel=None,
            labels=self.a,
            logits=self._pi[n_class])
          self.total_loss.append(tf.reduce_mean(loss)) #TODO: might tf.reduce_mean here

  def run_policy_and_value(self, sess, s_t):
    raise NotImplementedError()

  def run_policy(self, sess, s_t):
    pi_out = sess.run( self.pi, feed_dict = {self.s : [s_t]} )
    return pi_out

  def run_value(self, sess, s_t):
    raise NotImplementedError()

  def get_vars(self):
    if self.use_mnih_2015:
      return [self.W_conv1, self.b_conv1,
              self.W_conv2, self.b_conv2,
              self.W_conv3, self.b_conv3,
              self.W_fc1, self.b_fc1,
              self.W_fc2, self.b_fc2]
    else:
      return [self.W_conv1, self.b_conv1,
              self.W_conv2, self.b_conv2,
              self.W_fc1, self.b_fc1,
              self.W_fc2, self.b_fc2]

  def load(self, sess=None, checkpoint=''):
    assert sess != None
    assert checkpoint != ''
    self.saver.restore(sess, checkpoint)
    print (colored("Successfully loaded: {}".format(checkpoint), "green"))

  def prepare_evaluate(self):
    with self.graph.as_default():
      with tf.device(self._device):
        self.accuracy = []
        for n_class in range(self._action_size):
          correct_prediction = tf.equal(tf.argmax(self._pi[n_class], 1), tf.argmax(self.a, 1))
          self.accuracy.append(tf.reduce_mean(tf.cast(correct_prediction, tf.float32)))
