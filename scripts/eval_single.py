import os
import sys
import numpy as np
from datetime import datetime
import importlib.util
import argparse


# pytorch stuff
import torch
import torch.nn as nn
import torch.optim as optim
from torch.optim import lr_scheduler

BASE_DIR = os.path.dirname(
    os.path.abspath("/home/yildirir/workspace/votenet/README.md")
)

ROOT_DIR = BASE_DIR
sys.path.append(os.path.join(ROOT_DIR, "utils"))
sys.path.append(os.path.join(ROOT_DIR, "pointnet2"))
sys.path.append(os.path.join(ROOT_DIR, "models"))
sys.path.append(BASE_DIR)

np.random.seed(31)
# project stuff
from dump_helper import (
    dump_results_for_sanity_check,
    dump_results_mini,
    dump_only_boxes,
    dump_only_boxes_gt,
)
from ap_helper import (
    APCalculator,
    parse_predictions,
    parse_groundtruths,
    parse_predictions_with_log_var,
)
from initialization_utils import (
    initialize_dataloader,
    initialize_model,
    log_string,
)


def evaluate_with_sampling(FLAGS):
    net, criterion, optimizer, bnm_scheduler = initialize_model(FLAGS)
    net.eval()
    # TODO: D eal with dropouts, for now they are closed
    CONFIG_DICT = {
        "remove_empty_box": False,
        "use_3d_nms": True,
        "nms_iou": 0.25,
        "use_old_type_nms": False,
        "cls_nms": True,
        "per_class_proposal": False,
        "conf_thresh": 0.8,
        "dataset_config": FLAGS.DATASET_CONFIG,
    }

    stat_dict = {}  # collect statistics
    FLAGS.TEST_DATALOADERS = [FLAGS.TEST_DATALOADER]
    for T in FLAGS.TEST_DATALOADERS:
        ap_calculator = APCalculator(
            ap_iou_thresh=FLAGS.AP_IOU_THRESH,
            class2type_map=FLAGS.DATASET_CONFIG.class2type,
        )

        for batch_idx, batch_data_label in enumerate(T):
            if batch_idx % 10 == 0:
                print("Eval batch: %d" % (batch_idx))
            for key in batch_data_label:
                if key != "name":
                    batch_data_label[key] = batch_data_label[key].to(FLAGS.DEVICE)

            # Forward pass
            inputs = {
                "point_clouds": batch_data_label["point_clouds"],
                "name": batch_data_label["name"],
            }
            print(inputs)
            # inputs = {'point_clouds': batch_data_label['point_clouds']}
            with torch.no_grad():
                end_points = net(inputs)

            # Compute loss8
            for key in batch_data_label:
                assert key not in end_points
                end_points[key] = batch_data_label[key]
            loss, end_points = criterion(end_points, FLAGS.DATASET_CONFIG)

            # Accumulate statistics and prin t out
            # t ot
            for key in end_points:
                if "loss" in key or "acc" in key or "ratio" in key:
                    if key not in stat_dict:
                        stat_dict[key] = 0
                    stat_dict[key] += end_points[key].item()

            batch_pred_map_cls, selected_raw_boxes = parse_predictions_with_log_var(
                end_points, CONFIG_DICT
            )
            # print(batch_pred_map_cls)
            batch_gt_map_cls = parse_groundtruths(end_points, CONFIG_DICT)
            ap_calculator.step(batch_pred_map_cls, batch_gt_map_cls)

            # Dump evaluation results for visualization
            # if FLAGS.DUMP_RESULTS and batch_idx == 0 and EPOCH_CNT % 10 == 0:
            # FLAGS.MODEL.DUMP_RESULTS(end_points, FLAGS.DUMP_DIR, FLAGS.DATASET_CONFIG)
        # Log statistics

        # FLAGS.TEST_VISUALIZER.log_scalars(
        #     {key: stat_dict[key] / float(batch_idx + 1) for key in stat_dict},
        #     (EPOCH_CNT + 1) * len(FLAGS.TRAIN_DATALOADER) * FLAGS.BATCH_SIZE,
        # )
        for key in sorted(stat_dict.keys()):
            log_string(
                FLAGS.LOGGER,
                "eval mean %s: %f" % (key, stat_dict[key] / (float(batch_idx + 1))),
            )

        # Evaluate average precision
        metrics_dict = ap_calculator.compute_metrics()
        for key in metrics_dict:
            log_string(FLAGS.LOGGER, "eval %s: %f" % (key, metrics_dict[key]))
        dump_results_mini(
            end_points,
            config=FLAGS.DATASET_CONFIG,
            dump_dir=FLAGS.DUMP_DIR + str(T.dataset.thresh),
        )

        dump_only_boxes(selected_raw_boxes, FLAGS.DUMP_DIR)
        dump_only_boxes_gt(batch_gt_map_cls, FLAGS.DUMP_DIR)


def save_datas(FLAGS):
    net, criterion, optimizer, bnm_scheduler = initialize_model(FLAGS)
    net.eval()
    CONFIG_DICT = {
        "remove_empty_box": False,
        "use_3d_nms": True,
        "nms_iou": 0.25,
        "use_old_type_nms": False,
        "cls_nms": True,
        "per_class_proposal": False,
        "conf_thresh": 0.8,
        "dataset_config": FLAGS.DATASET_CONFIG,
    }

    stat_dict = {}  # collect statistics
    FLAGS.TEST_DATALOADERS = [FLAGS.TEST_DATALOADER]
    for T in FLAGS.TEST_DATALOADERS:
        ap_calculator = APCalculator(
            ap_iou_thresh=FLAGS.AP_IOU_THRESH,
            class2type_map=FLAGS.DATASET_CONFIG.class2type,
        )

        for batch_idx, batch_data_label in enumerate(T):
            if batch_idx % 10 == 0:
                print("Eval batch: %d" % (batch_idx))
            for key in batch_data_label:
                if key != "name":
                    batch_data_label[key] = batch_data_label[key].to(FLAGS.DEVICE)

            # Forward pass
            inputs = {
                "point_clouds": batch_data_label["point_clouds"],
                "name": batch_data_label["name"],
            }
            # inputs = {'point_clouds': batch_data_label['point_clouds']}
            with torch.no_grad():
                end_points = net(inputs)

            # Compute loss8
            for key in batch_data_label:
                assert key not in end_points
                end_points[key] = batch_data_label[key]
            loss, end_points = criterion(end_points, FLAGS.DATASET_CONFIG)

            # Accumulate statistics and prin t out
            # t ot
            for key in end_points:
                if "loss" in key or "acc" in key or "ratio" in key:
                    if key not in stat_dict:
                        stat_dict[key] = 0
                    stat_dict[key] += end_points[key].item()

            batch_pred_map_cls = parse_predictions(end_points, CONFIG_DICT)
            batch_gt_map_cls = parse_groundtruths(end_points, CONFIG_DICT)
            ap_calculator.step(batch_pred_map_cls, batch_gt_map_cls)

            # Dump evaluation results for visualization
            # if FLAGS.DUMP_RESULTS and batch_idx == 0 and EPOCH_CNT % 10 == 0:
            # FLAGS.MODEL.DUMP_RESULTS(end_points, FLAGS.DUMP_DIR, FLAGS.DATASET_CONFIG)
        # Log statistics

        # FLAGS.TEST_VISUALIZER.log_scalars(
        #     {key: stat_dict[key] / float(batch_idx + 1) for key in stat_dict},
        #     (EPOCH_CNT + 1) * len(FLAGS.TRAIN_DATALOADER) * FLAGS.BATCH_SIZE,
        # )

        for key in sorted(stat_dict.keys()):
            log_string(
                FLAGS.LOGGER,
                "eval mean %s: %f" % (key, stat_dict[key] / (float(batch_idx + 1))),
            )

        # Evaluate average precision
        metrics_dict = ap_calculator.compute_metrics()
        for key in metrics_dict:
            log_string(FLAGS.LOGGER, "eval %s: %f" % (key, metrics_dict[key]))
        dump_results_mini(
            end_points,
            config=FLAGS.DATASET_CONFIG,
            dump_dir=FLAGS.DUMP_DIR + str(T.dataset.thresh),
        )


if __name__ == "__main__":

    parser = argparse.ArgumentParser()
    parser.add_argument("--config-path")
    args = parser.parse_args()

    spec = importlib.util.spec_from_file_location("C", args.config_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    FLAGS = mod.C

    initialize_dataloader(FLAGS)
    # save_datas(FLAGS)
    evaluate_with_sampling(FLAGS)
