# Copyright (c) Facebook, Inc. and its affiliates.
# 
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

'''Code adapted from https://github.com/junyanz/pytorch-CycleGAN-and-pix2pix'''
import os
import time
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.append(BASE_DIR)
import tf_logger


class Visualizer():
    def __init__(self, FLAGS, name='train'):
        # self.opt = opt
        #self.logger = tf_logger.Logger(os.path.join(FLAGS.logging_dir, FLAGS.name))
        #self.log_name = os.path.join(FLAGS.checkpoint_dir, FLAGS.name, 'loss_log.txt')

        self.logger = tf_logger.MyLogger(os.path.join(FLAGS.LOG_DIR, name))
        print(self.logger.writer.log_dir)
        self.log_name = os.path.join(FLAGS.LOG_DIR, 'tf_visualizer_log.txt')
        with open(self.log_name, "a") as log_file:
            now = time.strftime("%c")
            log_file.write('================ Training Loss (%s) ================\n' % now)

    # |visuals|: dictionary of images to save
    def log_images(self, visuals, step):
            for label, image_numpy in visuals.items():
                self.logger.image_summary(
                    label, [image_numpy], step=step)

    def plot_sum(self,tag,fig,step):
        self.logger.plot_summary(tag,fig,step)
    #     tb.add_figure("Mean Objectness Accuracies",fig,0)
    # scalars: dictionary of scalar labels and values
    def log_scalars(self, scalars, step):
        for label, val in scalars.items():
            self.logger.scalar_summary(label, val, step=step)

    # scatter plots
    def plot_current_points(self, points, disp_offset=10):
        pass

    # scalars: same format as |scalars| of plot_current_scalars
    def print_current_scalars(self, epoch, i, scalars):
        message = '(epoch: %d, iters: %d) ' % (epoch, i)
        for k, v in scalars.items():
            message += '%s: %.3f ' % (k, v)

        print(message)
        with open(self.log_name, "a") as log_file:
            log_file.write('%s\n' % message)
