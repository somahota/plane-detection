# Author: Yuanwei Li (3 Oct 2018)
#
# Standard scan plane detection in 3D ultrasound images of fetal head
# Network training
#
# In this script, we use quaternions to represent rotation.
#
# Reference
# Standard Plane Detection in 3D Fetal Ultrasound Using an Iterative Transformation Network
# https://arxiv.org/abs/1806.07486
#
# ==============================================================================

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import numpy as np
import tensorflow as tf
from utils import input_data, network, geometry, plane


class Config(object):
    """Training configurations."""
    # File paths
    data_dir = './data/Images'
    label_dir = './data/Landmarks'
    train_list_file = './data/list_train.txt'
    test_list_file = './data/list_test.txt'
    log_dir = './logs'
    model_dir = './cnn_model'
    # General parameters
    plane_name = 'tv'                           # Plane name: 'tv' or 'tc'
    box_size = np.array([225, 225])             # plane size (odd number)
    input_plane = 3                             # Number of planes as input images. 1: one plane image. 3: three orthogonal plane images
    landmark_count = 16                         # Number of landmarks
    # Training parameters
    resume = False                              # Whether to train from scratch or resume previous training
    learning_rate = 0.001
    max_steps = 100000                          # Number of steps to train
    save_interval = 25000                       # Number of steps in between saving each model
    batch_size = 64                             # Training batch size
    dropout = 0.5
    # Parameters for sampling training plane
    trans_frac = 0.6                            # Percentage of middle volume to sample plane centre from. (0-1)
    max_euler = [45.0/180.0*np.pi,              # Maximum range to sample the three Euler angles in radians for plane orientation.
                 45.0/180.0*np.pi,
                 45.0/180.0*np.pi]
    # Weightings given to different loss terms.
    alpha = 1                                   # translation classification loss
    beta = 1                                    # translation regression loss
    gamma = 1                                   # rotation classification loss
    delta = 1                                   # rotation regression loss


def main():
    config = Config()
    num_output_tc = 6
    num_output_tr = 3
    num_output_rc = 6
    num_output_rr = 4

    # Load images and ground truth planes
    data = input_data.read_data_sets(config.data_dir,
                                     config.label_dir,
                                     config.train_list_file,
                                     config.test_list_file,
                                     config.landmark_count,
                                     config.plane_name)

    # Build graph
    print("Building graph...")
    # Input placeholders
    with tf.name_scope('input'):
        x = tf.placeholder(tf.float32, [None, config.box_size[0], config.box_size[1], config.input_plane], name='x-input')
        tf.add_to_collection('x', x)
        ytc_ = tf.placeholder(tf.float32, [None, num_output_tc], name='ytc-input')     # translation classification output
        tf.add_to_collection('ytc_', ytc_)
        ytr_ = tf.placeholder(tf.float32, [None, num_output_tr], name='ytr-input')     # translation regression output
        tf.add_to_collection('ytr_', ytr_)
        yrc_ = tf.placeholder(tf.float32, [None, num_output_rc], name='yrc-input')     # rotation classification prob output
        tf.add_to_collection('yrc_', yrc_)
        yrr_ = tf.placeholder(tf.float32, [None, num_output_rr], name='yrr-input')     # rotation regression (quaternions) output
        tf.add_to_collection('yrr_', yrr_)

    # Define CNN model
    ytc, ytr, yrc, yrr, keep_prob = network.cnn(x, config.input_plane, num_output_tc, num_output_tr, num_output_rc, num_output_rr)
    tf.add_to_collection('ytc', ytc)
    tf.add_to_collection('ytr', ytr)
    tf.add_to_collection('yrc', yrc)
    tf.add_to_collection('yrr', yrr)
    tf.add_to_collection('keep_prob', keep_prob)

    # Define prediction
    with tf.name_scope('prediction'):
        action_ind_tran = tf.argmax(ytc, 1)
        tf.add_to_collection('action_ind_tran', action_ind_tran)
        action_prob_tran = tf.nn.softmax(ytc)
        tf.add_to_collection('action_prob_tran', action_prob_tran)
        action_ind_rot = tf.argmax(yrc, 1)
        tf.add_to_collection('action_ind_rot', action_ind_rot)
        action_prob_rot = tf.nn.softmax(yrc)
        tf.add_to_collection('action_prob_rot', action_prob_rot)

    # Define loss
    with tf.name_scope('loss'):
        # Weightings for each loss term
        alpha = tf.placeholder(tf.float32, name='alpha')
        tf.add_to_collection('alpha', alpha)
        beta = tf.placeholder(tf.float32, name='beta')
        tf.add_to_collection('beta', beta)
        gamma = tf.placeholder(tf.float32, name='gamma')
        tf.add_to_collection('gamma', gamma)
        delta = tf.placeholder(tf.float32, name='delta')
        tf.add_to_collection('delta', delta)

        # translation classification loss (cross entropy)
        loss_tc = tf.nn.softmax_cross_entropy_with_logits(labels=ytc_, logits=ytc)
        loss_tc = tf.reduce_mean(loss_tc)
        tf.add_to_collection('loss_tc', loss_tc)
        tf.summary.scalar('loss_tc', loss_tc)

        # translation regresssion loss (MSE)
        loss_tr = tf.reduce_sum(tf.pow(ytr_ - ytr, 2), axis=1)
        loss_tr = tf.reduce_mean(loss_tr)
        tf.add_to_collection('loss_tr', loss_tr)
        tf.summary.scalar('loss_tr', loss_tr)

        # rotation classification loss (cross entropy)
        loss_rc = tf.nn.softmax_cross_entropy_with_logits(labels=yrc_, logits=yrc)
        loss_rc = tf.reduce_mean(loss_rc)
        tf.add_to_collection('loss_rc', loss_rc)
        tf.summary.scalar('loss_rc', loss_rc)

        # rotation regression loss (MSE)
        yrr_norm = yrr / tf.expand_dims(tf.sqrt(tf.reduce_sum(tf.pow(yrr, 2), axis=1)), axis=1)
        tf.add_to_collection('yrr_norm', yrr_norm)
        loss_rr = tf.reduce_sum(tf.pow(yrr_ - yrr_norm, 2), axis=1)
        loss_rr = tf.reduce_mean(loss_rr)
        tf.add_to_collection('loss_rr', loss_rr)
        tf.summary.scalar('loss_rr', loss_rr)

        # Combined loss
        loss = alpha * loss_tc + beta * loss_tr + gamma * loss_rc + delta * loss_rr
        tf.add_to_collection('loss', loss)
        tf.summary.scalar('loss', loss)

    # Define optimizer
    with tf.name_scope('train'):
        # Learning rate decreases over time
        # global_step = tf.Variable(0, trainable=False)
        # starter_learning_rate = config.learning_rate
        # learning_rate = tf.train.exponential_decay(starter_learning_rate, global_step, 25000, 0.5, staircase=True)
        # train_step = tf.train.AdamOptimizer(learning_rate).minimize(loss, global_step=global_step)
        # tf.summary.scalar('learning_rate', learning_rate)
        # Constant learning rate
        train_step = tf.train.AdamOptimizer(config.learning_rate).minimize(loss)
        tf.add_to_collection('train_step', train_step)

    with tf.name_scope('performance'):
        # translation classification accuracy
        correct_classification_tran = tf.equal(tf.argmax(ytc, 1), tf.argmax(ytc_, 1))
        correct_classification_tran = tf.cast(correct_classification_tran, tf.float32)
        accuracy_tran = tf.reduce_mean(correct_classification_tran)
        tf.add_to_collection('accuracy_tran', accuracy_tran)
        tf.summary.scalar('accuracy_tran', accuracy_tran)
        # rotation classification accuracy
        correct_classification_rot = tf.equal(tf.argmax(yrc, 1), tf.argmax(yrc_, 1))
        correct_classification_rot = tf.cast(correct_classification_rot, tf.float32)
        accuracy_rot = tf.reduce_mean(correct_classification_rot)
        tf.add_to_collection('accuracy_rot', accuracy_rot)
        tf.summary.scalar('accuracy_rot', accuracy_rot)


    # Run training
    print("Start training...")
    sess = tf.InteractiveSession()
    merged = tf.summary.merge_all()
    train_writer = tf.summary.FileWriter(config.log_dir + '/train', sess.graph)
    test_writer = tf.summary.FileWriter(config.log_dir + '/test')

    if config.resume:
        # Resume previous training
        saver = tf.train.Saver()
        saver.restore(sess, tf.train.latest_checkpoint(config.model_dir))
        saver = tf.train.Saver(max_to_keep=20)
        ite_start = int(tf.train.latest_checkpoint(config.model_dir).split('-')[-1])
        ite_end = ite_start + config.max_steps
    else:
        # Start new training
        tf.global_variables_initializer().run()
        saver = tf.train.Saver(max_to_keep=20)
        ite_start = 0
        ite_end = config.max_steps

    for i in xrange(ite_start, ite_end):
        slices_train, actions_tran_train, tran_diff_train, actions_rot_train, rot_diff_train = get_train_pairs(config, data.train)

        if i % 10 == 0:
            # Record summaries and test-set loss
            slices_test, actions_tran_test, tran_diff_test, actions_rot_test, rot_diff_test = get_train_pairs(config, data.test)

            summary_test, l_test, ltc_test, acc_t_test, ltr_test, lrc_test, acc_r_test, lrr_test = sess.run([merged, loss, loss_tc, accuracy_tran, loss_tr, loss_rc, accuracy_rot, loss_rr],
                                                                                                            feed_dict={x: slices_test,
                                                                                                                       ytc_: actions_tran_test,
                                                                                                                       ytr_: tran_diff_test,
                                                                                                                       yrc_: actions_rot_test,
                                                                                                                       yrr_: rot_diff_test,
                                                                                                                       alpha: config.alpha,
                                                                                                                       beta: config.beta,
                                                                                                                       gamma: config.gamma,
                                                                                                                       delta: config.delta,
                                                                                                                       keep_prob: 1.0})
            test_writer.add_summary(summary_test, i)
            # Record summaries and train-set loss
            summary_train, l_train, ltc_train, acc_t_train, ltr_train, lrc_train, acc_r_train, lrr_train = sess.run([merged, loss, loss_tc, accuracy_tran, loss_tr, loss_rc, accuracy_rot, loss_rr],
                                                                                                                    feed_dict={x: slices_train,
                                                                                                                               ytc_: actions_tran_train,
                                                                                                                               ytr_: tran_diff_train,
                                                                                                                               yrc_: actions_rot_train,
                                                                                                                               yrr_: rot_diff_train,
                                                                                                                               alpha: config.alpha,
                                                                                                                               beta: config.beta,
                                                                                                                               gamma: config.gamma,
                                                                                                                               delta: config.delta,
                                                                                                                               keep_prob: 1.0})
            train_writer.add_summary(summary_train, i)
            print('Step {}: \ttrain: loss={:11.6f} loss_tc={:11.6f} acc_t={:8.6f} loss_tr={:11.6f} loss_rc={:11.6f} acc_r={:8.6f} loss_rr={:11.6f}. \ttest: loss={:11.6f} loss_tc={:11.6f} acc_t={:8.6f} loss_tr={:11.6f} loss_rc={:11.6f} acc_r={:8.6f} loss_rr={:11.6f}.'.format
                  (i, l_train, ltc_train, acc_t_train, ltr_train, lrc_train, acc_r_train, lrr_train, l_test, ltc_test, acc_t_test, ltr_test, lrc_test, acc_r_test, lrr_test))

        # Train one step
        _ = sess.run(train_step, feed_dict={x: slices_train,
                                            ytc_: actions_tran_train,
                                            ytr_: tran_diff_train,
                                            yrc_: actions_rot_train,
                                            yrr_: rot_diff_train,
                                            alpha: config.alpha,
                                            beta: config.beta,
                                            gamma: config.gamma,
                                            delta: config.delta,
                                            keep_prob: config.dropout})

        # Save trained model
        if ((i+1) % config.save_interval) == 0:
            saver.save(sess, os.path.join(config.model_dir, 'model'), global_step=i+1)
            print("Trained model save successfully in {} at step {}".format(os.path.join(config.model_dir, 'model'), i+1))

    train_writer.close()
    test_writer.close()
    sess.close()


def get_train_pairs(config, data):
    """Prepare training data.

    Args:
      batch_size: mini batch size
      images: list of img_count images. Each image is [width, height, depth, channel], [x,y,z,channel]
      trans_gt: 3D centre point of the ground truth plane wrt the volume centre as origin. [2, img_count, 3]. first dimension is the tv(0) or tc(1) plane
      rots_gt: Quaternions that rotate xy-plane to the GT plane. [2, img_count, 4]. first dimension is the tv(0) or tc(1) plane
      trans_frac: Percentage of middle volume to sample translation vector from. (0-1)
      max_euler: Maximum range of Euler angles to sample from. (+/- max_euler). [3]
      box_size: size of 2D plane. [x,y].
      input_plane: number of input planes (1 or 3)
      plane: TV(0) or TC(1)

    Returns:
      slices: 2D plane images. [batch_size, box_size[0], box_size[1], input_plane]
      actions_tran: [batch_size, 6] the GT classification probability for translation. Hard label, one-hot vector. Gives the axis about which to translate, ie. axis with biggest distance to GT
      trans_diff: [batch_size, 3]. 3D centre point of the ground truth plane wrt the centre of the randomly sampled plane as origin.
      actions_rot:[batch_size, 6] the GT classification probability for rotation. Hard label, one-hot vector. Gives the axis about which to rotate, ie. rotation axis with biggest rotation angle.
      rots_diff: [batch_size, 4]. Rotation that maps the randomly sampled plane to the GT plane.

    """
    images = data.images
    trans_gt = data.trans_vecs
    rots_gt = data.quats
    batch_size = config.batch_size
    box_size = config.box_size
    input_plane = config.input_plane
    trans_frac = config.trans_frac
    max_euler = config.max_euler

    img_count = len(images)
    slices = np.zeros((batch_size, box_size[0], box_size[1], input_plane), np.float32)
    trans_diff = np.zeros((batch_size, 3))
    trans = np.zeros((batch_size, 3))
    rots_diff = np.zeros((batch_size, 4))
    rots = np.zeros((batch_size, 4))
    euler = np.zeros((batch_size, 6, 3))    # 6 Euler angle conventions. 'sxyz', 'sxzy', 'syxz', 'syzx', 'szxy', 'szyx'
    actions_tran = np.zeros((batch_size, 6), np.float32)
    actions_rot = np.zeros((batch_size, 6), np.float32)

    # get image indices randomly for a mini-batch
    ind = np.random.randint(img_count, size=batch_size)

    # Random uniform sampling of Euler angles with restricted range
    euler_angles = geometry.sample_euler_angles_fix_range(batch_size, max_euler[0], max_euler[1], max_euler[2])

    for i in xrange(batch_size):
        image = np.squeeze(images[ind[i]])
        img_siz = np.array(image.shape)

        # GT translation and quaternions
        tran_gt = trans_gt[ind[i], :]
        rot_gt = rots_gt[ind[i], :]

        # Randomly sample translation (plane centre) and quaternions
        tran = (np.random.rand(3) * (img_siz * trans_frac) + img_siz * (1-trans_frac) / 2.0) - ((img_siz-1) / 2.0)
        trans[i, :] = tran
        rot = geometry.quaternion_from_euler(euler_angles[i, 0], euler_angles[i, 1], euler_angles[i, 2], 'rxyz')
        rots[i, :] = rot


        ##### Extract plane image #####
        # Initialise identity plane and get orthogonal planes
        if input_plane == 1:
            xyz_coords = plane.init_mesh_by_plane(box_size, 'z')
        elif input_plane == 3:
            xyz_coords = plane.init_mesh_ortho(box_size)

        # Rotate and translate plane
        mat = geometry.quaternion_matrix(rot)
        mat[:3, 3] = tran
        xyz_coords = np.matmul(mat, xyz_coords)

        # Extract image plane
        if input_plane == 1:
            slices[i, :, :, 0], _ = plane.extract_plane_from_mesh(image, xyz_coords, box_size, 1)
        elif input_plane == 3:
            slice_single, _ = plane.extract_plane_from_mesh_batch(image, xyz_coords, box_size, 1)
            slices[i] = np.transpose(slice_single, (1, 2, 0))


        ##### Compute GT labels #####
        # Translation and rotation regression outputs. Compute difference in tran and quat between sampled plane and GT plane (convert to rotation matrices first)
        mat_inv = geometry.inv_mat(mat)
        mat_gt = geometry.quaternion_matrix(rot_gt)
        mat_gt[:3, 3] = tran_gt
        mat_diff = np.matmul(mat_inv, mat_gt)
        trans_diff[i, :] = mat_diff[:3, 3]
        rots_diff[i, :] = geometry.quaternion_from_matrix(mat_diff, isprecise=True)

        # Rotation classification output. Compute Euler angles for the six different conventions
        euler[i, 0, :] = np.array(geometry.euler_from_matrix(mat_diff, axes='sxyz'))
        euler[i, 1, :] = np.array(geometry.euler_from_matrix(mat_diff, axes='sxzy'))
        euler[i, 2, :] = np.array(geometry.euler_from_matrix(mat_diff, axes='syxz'))
        euler[i, 3, :] = np.array(geometry.euler_from_matrix(mat_diff, axes='syzx'))
        euler[i, 4, :] = np.array(geometry.euler_from_matrix(mat_diff, axes='szxy'))
        euler[i, 5, :] = np.array(geometry.euler_from_matrix(mat_diff, axes='szyx'))

    # Rotation classification output.
    max_ind_rot = np.argmax(np.abs(euler[:, :, 0]), axis=1)
    rot_x_max = np.logical_or(max_ind_rot == 0, max_ind_rot == 1)
    rot_y_max = np.logical_or(max_ind_rot == 2, max_ind_rot == 3)
    rot_z_max = np.logical_or(max_ind_rot == 4, max_ind_rot == 5)
    actions_ind_rot = np.zeros((batch_size), dtype=np.uint16)
    actions_ind_rot[rot_x_max] = 0
    actions_ind_rot[rot_y_max] = 1
    actions_ind_rot[rot_z_max] = 2
    max_euler = euler[np.arange(batch_size), max_ind_rot, np.zeros(batch_size, dtype=np.uint16)]   # [batch_size]
    is_positive = (max_euler > 0)
    actions_ind_rot[is_positive] = actions_ind_rot[is_positive] * 2
    actions_ind_rot[np.logical_not(is_positive)] = actions_ind_rot[np.logical_not(is_positive)] * 2 + 1
    actions_rot[np.arange(batch_size), actions_ind_rot] = 1

    # Translation classification output
    max_ind_tran = np.argmax(np.abs(trans_diff), axis=1)     # [batch_size]
    max_trans_diff = trans_diff[np.arange(batch_size), max_ind_tran]   # [batch_size]
    is_positive = (max_trans_diff > 0)
    actions_ind_tran = np.zeros((batch_size), dtype=np.uint16)
    actions_ind_tran[is_positive] = max_ind_tran[is_positive] * 2
    actions_ind_tran[np.logical_not(is_positive)] = max_ind_tran[np.logical_not(is_positive)] * 2 + 1
    actions_tran[np.arange(batch_size), actions_ind_tran] = 1

    return slices, actions_tran, trans_diff, actions_rot, rots_diff


if __name__ == '__main__':
    main()
