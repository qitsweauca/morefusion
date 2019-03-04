import chainer
import chainer.functions as F
import chainer.links as L
from chainercv.links.model.resnet import ResNet50
import numpy as np
import trimesh.transformations as tf

from .. import functions
from ..logger import logger


class SimpleMV3DCNNModel(chainer.Chain):

    def __init__(self):
        super(SimpleMV3DCNNModel, self).__init__()

        initialW = chainer.initializers.Normal(0.01)
        with self.init_scope():
            # MV
            self.res = ResNet50(arch='he', pretrained_model='imagenet')
            self.res.pick = ['res4']
            self.res.remove_unused()
            self.conv5 = L.Convolution2D(
                in_channels=1024,
                out_channels=16,
                ksize=1,
                initialW=initialW,
            )

            # voxelization_3d
            # -> (16, 32, 32, 32)
            self.voxel_dimensions = (32, 32, 32)
            self.voxel_channels = 16

            # 3DCNN
            self.conv6 = L.Convolution3D(
                in_channels=16,
                out_channels=16,
                ksize=8,
                stride=2,
                pad=3,
                initialW=initialW
            )  # 32x32x32 -> 16x16x16
            self.conv7 = L.Convolution3D(
                in_channels=16,
                out_channels=16,
                ksize=3,
                stride=2,
                pad=1,
                initialW=initialW
            )  # 16x16x16 -> 8x8x8

            # concat
            # (16, 8, 8, 8) + (16, 8, 8, 8) -> (32, 8, 8, 8)
            # 32 * 8 * 8 * 8 = 16384

            # FC
            self.fc8 = L.Linear(16384, 1024, initialW=initialW)
            self.fc_quaternion = L.Linear(1024, 4, initialW=initialW)
            self.fc_translation = L.Linear(1024, 3, initialW=initialW)

    def _encode_multiview(self, origin, pitch, rgbs, pcds, masks):
        batch_size = len(rgbs)
        assert batch_size == len(pcds)
        assert batch_size == len(masks)

        # MV
        mean = self.xp.asarray(self.res.mean)
        rgbs = rgbs - mean[None]
        h, = self.res(rgbs)
        logger.debug(f'h_res: {h.shape}')
        h = F.relu(self.conv5(h))
        logger.debug(f'h_conv5: {h.shape}')

        # Voxelization3D
        h = F.resize_images(h, rgbs.shape[2:])
        h_vox = []
        for i in range(batch_size):
            h_i = h[i].transpose(1, 2, 0)  # CHW -> HWC
            h_i = functions.voxelization_3d(
                values=h_i[masks[i], :],
                points=pcds[i][masks[i], :],
                origin=origin,
                pitch=pitch,
                dimensions=self.voxel_dimensions,
                channels=self.voxel_channels,
            )
            h_i = h_i.transpose(3, 0, 1, 2)  # XYZC -> CXYZ
            logger.debug(f'h_i, i={i}: {h_i.shape}')
            h_vox.append(h_i[None])
        h = F.concat(h_vox, axis=0)
        logger.debug(f'h_vox: {h.shape}')
        h = F.max(h, axis=0)[None]
        logger.debug(f'h_vox_fused: {h.shape}')  # NOQA

        # 3DCNN
        h = F.relu(self.conv6(h))
        logger.debug(f'h_conv6: {h.shape}')
        h = F.relu(self.conv7(h))
        logger.debug(f'h_conv7: {h.shape}')
        return h

    def _predict_pose(self, h_cad, h_scan):
        h = F.concat([h_cad, h_scan], axis=1)
        logger.debug(f'h_concat: {h.shape}')

        h = F.relu(self.fc8(h))
        logger.debug(f'h_fc8: {h.shape}')

        quaternion = F.sigmoid(self.fc_quaternion(h))
        logger.debug(f'quaternion: {quaternion}')
        translation = F.sigmoid(self.fc_translation(h))
        logger.debug(f'translation: {translation}')
        return translation, quaternion

    def __call__(
        self,
        *,
        class_id,
        pitch,
        gt_pose,
        cad_origin,
        cad_rgbs,
        cad_pcds,
        scan_origin,
        scan_rgbs,
        scan_pcds,
        scan_masks,
    ):
        if class_id == -1:
            # skip invalid data
            return chainer.Variable(self.xp.zeros((), dtype=np.float32))

        logger.debug('==> Arguments for SimpleMV3DCNNModel')
        logger.debug(f'class_id: {type(class_id)}, {class_id.shape}')
        logger.debug(f'pitch: {type(pitch)}, {pitch.shape}')
        logger.debug(f'gt_pose: {type(gt_pose)}, {gt_pose.shape}')
        logger.debug(f'cad_origin: {type(cad_origin)}, {cad_origin.shape}')
        logger.debug(f'cad_rgbs: {type(cad_rgbs)}, {cad_rgbs.shape}')
        logger.debug(f'cad_pcds: {type(cad_pcds)}, {cad_pcds.shape}')
        logger.debug(f'scan_origin: {type(scan_origin)}, {scan_origin.shape}')
        logger.debug(f'scan_rgbs: {type(scan_rgbs)}, {scan_rgbs.shape}')
        logger.debug(f'scan_pcds: {type(scan_pcds)}, {scan_pcds.shape}')
        logger.debug(f'scan_masks: {type(scan_masks)}, {scan_masks.shape}')

        batch_size = class_id.shape[0]
        assert batch_size == 1, 'single batch_size is only supported'
        pitch = pitch[0].astype(np.float32)
        gt_pose = gt_pose[0].astype(np.float32)

        logger.debug('==> Multi-View Encoding CAD')
        cad_origin = cad_origin[0].astype(np.float32)
        cad_rgbs = cad_rgbs[0].astype(np.float32).transpose(0, 3, 1, 2)
        cad_pcds = cad_pcds[0].astype(np.float32)
        cad_masks = ~self.xp.isnan(cad_pcds).any(axis=3)
        h_cad = self._encode_multiview(
            origin=cad_origin,
            pitch=pitch,
            rgbs=cad_rgbs,
            pcds=cad_pcds,
            masks=cad_masks,
        )

        logger.debug('==> Multi-View Encoding Scan')
        scan_origin = scan_origin[0].astype(np.float32)
        scan_rgbs = scan_rgbs[0].astype(np.float32).transpose(0, 3, 1, 2)
        scan_pcds = scan_pcds[0].astype(np.float32)
        scan_masks = scan_masks[0] & ~self.xp.isnan(scan_pcds).any(axis=3)
        h_scan = self._encode_multiview(
            origin=scan_origin,
            pitch=pitch,
            rgbs=scan_rgbs,
            pcds=scan_pcds,
            masks=scan_masks
        )

        logger.debug('==> Predicting Pose')
        translation, quaternion = self._predict_pose(h_cad, h_scan)

        logger.debug('==> Computing Loss')
        gt_pose = chainer.cuda.to_cpu(gt_pose)
        gt_quaternion = tf.quaternion_from_matrix(gt_pose)
        gt_quaternion = self.xp.asarray(gt_quaternion)
        gt_quaternion = gt_quaternion[None].astype(np.float32)  # (1, 4)
        logger.debug(f'gt_quaternion: {gt_quaternion}')

        gt_translation = tf.translation_from_matrix(gt_pose)
        gt_translation = self.xp.asarray(gt_translation)
        voxel_dimensions = self.xp.asarray(self.voxel_dimensions)
        gt_translation = (
            (gt_translation - scan_origin) / pitch / voxel_dimensions
        )
        gt_translation = gt_translation[None].astype(np.float32)  # (1, 3)
        logger.debug(f'gt_translation: {gt_translation}')

        loss_quaternion = F.mean_absolute_error(quaternion, gt_quaternion)
        loss_translation = F.mean_absolute_error(translation, gt_translation)
        loss = loss_quaternion + loss_translation
        logger.debug(f'loss_quaternion: {loss_quaternion}')
        logger.debug(f'loss_translation: {loss_translation}')
        logger.debug(f'loss: {loss}')

        chainer.report(
            values={
                'loss_quaternion': loss_quaternion,
                'loss_translation': loss_translation,
                'loss': loss,
            },
            observer=self,
        )

        return loss