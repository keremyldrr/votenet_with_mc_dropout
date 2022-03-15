# Copyright (c) Facebook, Inc. and its affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

""" Evaluation routine for 3D object detection with SUN RGB-D and ScanNet.
"""

import os
import sys
import numpy as np
import pdb
from datetime import datetime
import argparse
import importlib
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader

torch.multiprocessing.set_sharing_strategy("file_system")

BASE_DIR = os.path.dirname(os.path.abspath("/home/yildirir/workspace/votenet/models"))
ROOT_DIR = BASE_DIR
print(ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, "models"))
sys.path.append(os.path.join(ROOT_DIR, "utils"))
from ap_helper import APCalculator, parse_predictions, parse_groundtruths
from ap_helper import parse_predictions_with_log_var
from dump_helper import dump_only_boxes, dump_only_boxes_gt, dump_results_mini

parser = argparse.ArgumentParser()
parser.add_argument(
    "--model", default="votenet", help="Model file name [default: votenet]"
)
parser.add_argument(
    "--dataset",
    default="sunrgbd",
    help="Dataset name. sunrgbd or scannet. [default: sunrgbd]",
)
parser.add_argument(
    "--checkpoint_path", default=None, help="Model checkpoint path [default: None]"
)
parser.add_argument(
    "--dump_dir", default=None, help="Dump dir to save sample outputs [default: None]"
)
parser.add_argument(
    "--num_point", type=int, default=20000, help="Point Number [default: 20000]"
)
parser.add_argument(
    "--num_target", type=int, default=256, help="Point Number [default: 256]"
)
parser.add_argument(
    "--batch_size", type=int, default=8, help="Batch Size during training [default: 8]"
)
parser.add_argument(
    "--vote_factor",
    type=int,
    default=1,
    help="Number of votes generated from each seed [default: 1]",
)
parser.add_argument(
    "--cluster_sampling",
    default="vote_fps",
    help="Sampling strategy for vote clusters: vote_fps, seed_fps, random [default: vote_fps]",
)
parser.add_argument(
    "--ap_iou_thresholds",
    default="0.25,0.5",
    help="A list of AP IoU thresholds [default: 0.25,0.5]",
)
parser.add_argument(
    "--no_height", action="store_true", help="Do NOT use height signal in input."
)
parser.add_argument("--use_color", action="store_true", help="Use RGB color in input.")
parser.add_argument(
    "--use_sunrgbd_v2", action="store_true", help="Use SUN RGB-D V2 box labels."
)
parser.add_argument(
    "--use_3d_nms", action="store_true", help="Use 3D NMS instead of 2D NMS."
)
parser.add_argument("--use_cls_nms", action="store_true", help="Use per class NMS.")
parser.add_argument(
    "--use_old_type_nms", action="store_true", help="Use old type of NMS, IoBox2Area."
)
parser.add_argument(
    "--per_class_proposal",
    action="store_true",
    help="Duplicate each proposal num_class times.",
)
parser.add_argument(
    "--nms_iou", type=float, default=0.25, help="NMS IoU threshold. [default: 0.25]"
)
parser.add_argument(
    "--conf_thresh",
    type=float,
    default=0.05,
    help="Filter out predictions with obj prob less than it. [default: 0.05]",
)
parser.add_argument(
    "--faster_eval",
    action="store_true",
    help="Faster evaluation by skippling empty bounding box removal.",
)
parser.add_argument(
    "--shuffle_dataset", action="store_true", help="Shuffle the dataset (random order)."
)
parser.add_argument(
    "--overfit", action="store_true", help="Shuffle the dataset (random order)."
)
parser.add_argument(
    "--log_var", action="store_true", help="Shuffle the dataset (random order)."
)

parser.add_argument(
    "--thresholds",
    type=float,
    nargs="+",
    default=[0.3],
    help="thresholds for rejecting objects while loading frames",
)
parser.add_argument(
    "--num_samples",
    type=int,
    default=0,
    help="Number of samples",
)
FLAGS = parser.parse_args()

if FLAGS.use_cls_nms:
    assert FLAGS.use_3d_nms

# ------------------------------------------------------------------------- GLOBAL CONFIG BEG
BATCH_SIZE = FLAGS.batch_size
NUM_POINT = FLAGS.num_point
DUMP_DIR = FLAGS.dump_dir
CHECKPOINT_PATH = FLAGS.checkpoint_path
assert CHECKPOINT_PATH is not None
FLAGS.DUMP_DIR = DUMP_DIR
AP_IOU_THRESHOLDS = [float(x) for x in FLAGS.ap_iou_thresholds.split(",")]

# Prepare DUMP_DIR
if not os.path.exists(DUMP_DIR):
    os.mkdir(DUMP_DIR)
DUMP_FOUT = open(os.path.join(DUMP_DIR, "log_eval.txt"), "w")
DUMP_FOUT.write(str(FLAGS) + "\n")


def log_string(out_str):
    DUMP_FOUT.write(out_str + "\n")
    DUMP_FOUT.flush()

    # print(out_str)


# Init datasets and dataloaders
def my_worker_init_fn(worker_id):
    # np.random.seed(np.random.get_state()[1][0] + worker_id)
    np.random.seed(1)


if FLAGS.dataset == "sunrgbd":
    sys.path.append(os.path.join(ROOT_DIR, "sunrgbd"))
    from sunrgbd_detection_dataset import SunrgbdDetectionVotesDataset, MAX_NUM_OBJ
    from model_util_sunrgbd import SunrgbdDatasetConfig

    DATASET_CONFIG = SunrgbdDatasetConfig()
    TEST_DATASET = SunrgbdDetectionVotesDataset(
        "val",
        num_points=NUM_POINT,
        augment=False,
        use_color=FLAGS.use_color,
        use_height=(not FLAGS.no_height),
        use_v1=(not FLAGS.use_sunrgbd_v2),
    )
elif FLAGS.dataset == "scannet":
    sys.path.append(os.path.join(ROOT_DIR, "scannet"))
    from scannet_detection_dataset import ScannetDetectionDataset, MAX_NUM_OBJ
    from model_util_scannet import ScannetDatasetConfig

    DATASET_CONFIG = ScannetDatasetConfig()
    TEST_DATASET = ScannetDetectionDataset(
        "val",
        num_points=NUM_POINT,
        augment=False,
        use_color=FLAGS.use_color,
        use_height=(not FLAGS.no_height),
    )
elif FLAGS.dataset == "scannet_frames":

    sys.path.append(os.path.join(ROOT_DIR, "scannet"))
    sys.path.append(os.path.join(ROOT_DIR, "scannet"))
    from scannet_frames_dataset import ScannetDetectionFramesDataset, MAX_NUM_OBJ
    from model_util_scannet import ScannetDatasetConfig

    DATASET_CONFIG = ScannetDatasetConfig()
    DATASET_CONFIG.num_samples = FLAGS.num_samples
    data_setting = {
        "dataset_path": "/home/yildirir/workspace/kerem/TorchSSC/DATA/ScanNet/",
        "train_source": "/home/yildirir/workspace/kerem/TorchSSC/DATA/ScanNet/train_frames.txt",
        "eval_source": "/home/yildirir/workspace/kerem/TorchSSC/DATA/ScanNet/val_frames.txt",
        "frames_path": "/home/yildirir/workspace/kerem/TorchSSC/DATA/scannet_frames_25k/",
    }

    TEST_DATASETS = [
        ScannetDetectionFramesDataset(
            data_setting,
            split_set="val",
            num_points=NUM_POINT,
            use_color=False,
            use_height=True,
            augment=False,
            thresh=t,
            overfit=FLAGS.overfit,
        )
        for t in FLAGS.thresholds
    ]

else:
    print("Unknown dataset %s. Exiting..." % (FLAGS.dataset))
    exit(-1)
print([len(T) for T in TEST_DATASETS])

# TODO: add sampler here :with expression as target:
TEST_DATALOADERS = [
    DataLoader(
        T,
        batch_size=BATCH_SIZE,
        shuffle=FLAGS.shuffle_dataset,
        num_workers=4,
        worker_init_fn=my_worker_init_fn,
    )
    for T in TEST_DATASETS
]

# Init the model and optimzier
FLAGS.DATASET_CONFIG = DATASET_CONFIG
MODEL = importlib.import_module(FLAGS.model)  # import network module

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
num_input_channel = int(FLAGS.use_color) * 3 + int(not FLAGS.no_height) * 1

if FLAGS.model == "boxnet":
    Detector = MODEL.BoxNet
else:
    Detector = MODEL.VoteNet

FLAGS.LOG_VAR = FLAGS.log_var
net = Detector(
    num_class=DATASET_CONFIG.num_class,
    num_heading_bin=DATASET_CONFIG.num_heading_bin,
    num_size_cluster=DATASET_CONFIG.num_size_cluster,
    mean_size_arr=DATASET_CONFIG.mean_size_arr,
    num_proposal=FLAGS.num_target,
    input_feature_dim=num_input_channel,
    vote_factor=FLAGS.vote_factor,
    sampling=FLAGS.cluster_sampling,
    log_var=FLAGS.LOG_VAR,
)
net.to(device)
criterion = MODEL.get_loss

# Load the Adam optimizer
optimizer = optim.Adam(net.parameters(), lr=0.001)

# Load checkpoint if there is any
if CHECKPOINT_PATH is not None and os.path.isfile(CHECKPOINT_PATH):
    checkpoint = torch.load(CHECKPOINT_PATH)
    net.load_state_dict(checkpoint["model_state_dict"])
    optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
    epoch = checkpoint["epoch"]
    log_string("Loaded checkpoint %s (epoch: %d)" % (CHECKPOINT_PATH, epoch))

# Used for AP calculation
CONFIG_DICT = {
    "remove_empty_box": (not FLAGS.faster_eval),
    "use_3d_nms": FLAGS.use_3d_nms,
    "nms_iou": FLAGS.nms_iou,
    "use_old_type_nms": FLAGS.use_old_type_nms,
    "cls_nms": FLAGS.use_cls_nms,
    "per_class_proposal": FLAGS.per_class_proposal,
    "conf_thresh": FLAGS.conf_thresh,
    "dataset_config": DATASET_CONFIG,
    "num_samples": FLAGS.num_samples,
}

# ------------------------------------------------------------------------- GLOBAL CONFIG END
print(CONFIG_DICT)
print(FLAGS)


def evaluate_one_epoch():
    for TEST_DATALOADER in TEST_DATALOADERS:
        print(
            "------------------------------------------{}-------------------------------------------".format(
                TEST_DATALOADER.dataset.thresh
            )
        )
        stat_dict = {}
        ap_calculator_list_visibility = []
        counts = []
        for vt in TEST_DATASETS[0].bin_thresholds:
            ap_calculator_list = [
                APCalculator(iou_thresh, DATASET_CONFIG.class2type)
                for iou_thresh in AP_IOU_THRESHOLDS
            ]
            ap_calculator_list_visibility.append(ap_calculator_list)
            counts.append([0, 0])
        net.eval()  # set model to eval mode (for bn and dp)

        for batch_idx, batch_data_label in enumerate(TEST_DATALOADER):
            if batch_idx % 10 == 0:

                print("Eval batch: %d" % (batch_idx))
            # if batch_idx > 2:
            #     break
            for key in batch_data_label:
                try:
                    batch_data_label[key] = batch_data_label[key].to(device)
                except Exception as e:
                    # print(e)
                    continue
            # Forward pass
            inputs = {"point_clouds": batch_data_label["point_clouds"]}
            with torch.no_grad():
                end_points = net(inputs)

            # Compute loss
            for key in batch_data_label:
                assert key not in end_points
                end_points[key] = batch_data_label[key]
            loss, end_points = criterion(end_points, DATASET_CONFIG)
            # print(loss)
            # Accumulate statistics and print out
            for key in end_points:
                if "loss" in key or "acc" in key or "ratio" in key:
                    if key not in stat_dict:
                        stat_dict[key] = 0
                    stat_dict[key] += end_points[key].item()

            # batch_pred_map_cls = parse_predictions(end_points, CONFIG_DICT)

            # import trgccimesh

            # FIXME introduce a nice structure for parse preds. Right now batch pred_map_
            # cls is a list of lists
            batch_pred_map_cls = parse_predictions_with_log_var(end_points, CONFIG_DICT)
            batch_gt_map_cls = np.array(
                [
                    np.array(a, dtype=object)
                    for a in parse_groundtruths(end_points, CONFIG_DICT)
                ],
                dtype=object,
            )
            bsize = len(batch_data_label["vis_masks"])
            visible_gts = [[] for i in range(len(ap_calculator_list_visibility))]

            for bidx in range(bsize):
                for ii, mask in enumerate(batch_data_label["vis_masks"][bidx]):

                    # pdb.set_trace()
                    visible_gts[ii].append(
                        batch_gt_map_cls[bidx][torch.where(mask != 0)[0].cpu().numpy()]
                    )

            # print("*************")!
            # for a in batch_pred_map_cls[0]:
            #     print(a[0], a[2], a[1].mean(0))
            # batch_pred_map_cls = [batch_pred_map_cls] * 3
            batch_gt_map_cls = visible_gts
            for vidx, ap_calculator_list in enumerate(ap_calculator_list_visibility):
                for ap_calculator in ap_calculator_list:
                    ap_calculator.step(batch_pred_map_cls[vidx], batch_gt_map_cls[vidx])
                # pdb.set_trace()
                counts[vidx][0] += np.sum(
                    [len(batch_pred_map_cls[vidx][i]) for i in range(bsize)]
                )  # import trimesh
                counts[vidx][1] += np.sum(
                    [len(batch_gt_map_cls[vidx][i]) for i in range(bsize)]
                )  # import trimesh

            for idx, pc in enumerate(batch_data_label["point_clouds"]):
                filename = os.path.join(
                    FLAGS.DUMP_DIR, "{}.ply".format(batch_data_label["name"][idx])
                )
            # trimesh.points.PointCloud(pc[:, :3].cpu().numpy()).export(filename)

            # dump_only_boxes(selected_raw_boxes, FLAGS.DUMP_DIR)
            # dump_only_boxe s_gt(batch_gt_map_cls, FLAGS.DUMP_DIR)
            # print(FLAGS.DUMP_DIR)
            # Dump evaluation results for visualization
            # if batch_idx == 0:
            #     MODEL.dump_results(end_points, DUMP_DIR, DATASET_CONFIG)
            # if batch_idx >20:
            #     break
        # Log statistics

        for key in sorted(stat_dict.keys()):
            log_string(
                "eval mean %s: %f" % (key, stat_dict[key] / (float(batch_idx + 1)))
            )

        # Evaluate average precision
        for ind, ap_calculator_list in enumerate(ap_calculator_list_visibility):

            print(
                "-" * 10,
                "vis_thresh: %f" % (TEST_DATASETS[0].bin_thresholds[ind]),
                "-" * 10,
            )
            for i, ap_calculator in enumerate(ap_calculator_list):
                print("-" * 10, "iou_thresh: %f" % (AP_IOU_THRESHOLDS[i]), "-" * 10)
                metrics_dict = ap_calculator.compute_metrics()
                for key in metrics_dict:
                    if key == "mAP" or key == "AR":
                        print("%s: %f" % (key, metrics_dict[key]))
                    log_string("eval %s: %f" % (key, metrics_dict[key]))
            # print("SKIPPING STATS")

        mean_loss = stat_dict["loss"] / float(batch_idx + 1)
        print(counts)
        return mean_loss


def eval():
    log_string(str(datetime.now()))
    # Reset numpy seed.
    # REF: https://github.com/pytorch/pytorch/issues/5059
    np.random.seed(1)
    loss = evaluate_one_epoch()


if __name__ == "__main__":
    eval()
