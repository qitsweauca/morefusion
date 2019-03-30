import imgviz
import numpy as np
import trimesh.transformations as tf

import objslampp


class Dataset(objslampp.datasets.base.DatasetBase):

    _root_dir = objslampp.datasets.YCBVideoDataset._root_dir

    def __init__(self, split, class_ids=None):
        super().__init__()
        assert split in ('train', 'val')
        self._split = split
        self._class_ids = class_ids
        self._ids = self.get_ids(split=split)

    def get_ids(
        self,
        split: str,
    ):
        assert split in ('train', 'val')

        if split == 'val':
            ids = objslampp.datasets.YCBVideoDataset(
                split='keyframe'
            ).get_ids()
        else:
            assert split == 'train'
            ids = objslampp.datasets.YCBVideoDataset(
                split='train'
            ).get_ids(sampling=8)

        ids = [(True, x) for x in ids]

        if split == 'train':
            ids_syn = objslampp.datasets.YCBVideoSyntheticDataset().get_ids()
            ids_syn = [(False, x) for x in ids_syn]
            ids += ids_syn

        return tuple(ids)

    def _get_invalid_data(self):
        return dict(
            class_id=-1,
            rgb=np.zeros((256, 256, 3), dtype=np.uint8),
            pcd=np.zeros((256, 256, 3), dtype=np.float64),
            quaternion_true=np.zeros((4,), dtype=np.float64),
            translation_true=np.zeros((3,), dtype=np.float64),
        )

    def get_example(self, index):
        is_real, image_id = self._ids[index]

        if is_real:
            frame = objslampp.datasets.YCBVideoDataset.get_frame(image_id)
        else:
            frame = objslampp.datasets.YCBVideoSyntheticDataset.get_frame(
                image_id
            )

        class_ids = frame['meta']['cls_indexes']

        if self._class_ids is None:
            class_id = np.random.choice(class_ids)
        elif not any(c in class_ids for c in self._class_ids):
            return self._get_invalid_data()
        else:
            class_id = np.random.choice(self._class_ids)

        instance_id = np.where(class_ids == class_id)[0][0]

        mask = frame['label'] == class_id
        if mask.sum() == 0:
            return self._get_invalid_data()

        bbox = objslampp.geometry.masks_to_bboxes([mask])[0]
        y1, x1, y2, x2 = bbox.round().astype(int)
        if (y2 - y1) * (x2 - x1) == 0:
            return self._get_invalid_data()

        rgb = frame['color'].copy()
        rgb[~mask] = 0
        rgb = rgb[y1:y2, x1:x2]
        rgb = imgviz.centerize(rgb, (256, 256))

        depth = frame['depth']
        K = frame['meta']['intrinsic_matrix']
        pcd = objslampp.geometry.pointcloud_from_depth(
            depth, fx=K[0, 0], fy=K[1, 1], cx=K[0, 2], cy=K[1, 2],
        )
        pcd[~mask] = np.nan
        pcd = pcd[y1:y2, x1:x2]
        pcd = imgviz.centerize(pcd, (256, 256), cval=np.nan)
        if np.isnan(pcd).any(axis=2).all():
            return self._get_invalid_data()

        T_cad2cam = frame['meta']['poses'][:, :, instance_id]
        quaternion_true = tf.quaternion_from_matrix(T_cad2cam)
        translation_true = tf.translation_from_matrix(T_cad2cam)

        return dict(
            class_id=class_id,
            rgb=rgb,
            pcd=pcd,
            quaternion_true=quaternion_true,
            translation_true=translation_true,
        )


if __name__ == '__main__':
    dataset = Dataset(split='train', class_ids=[2])
    print(f'dataset_size: {len(dataset)}')

    def images():
        for i in range(0, len(dataset)):
            example = dataset[i]
            print(f"class_id: {example['class_id']}")
            print(f"quaternion_true: {example['quaternion_true']}")
            print(f"translation_true: {example['translation_true']}")
            if example['class_id'] > 0:
                viz = imgviz.tile([
                    example['rgb'],
                    imgviz.depth2rgb(example['pcd'][:, :, 0]),
                    imgviz.depth2rgb(example['pcd'][:, :, 1]),
                    imgviz.depth2rgb(example['pcd'][:, :, 2]),
                ], (1, 4), border=(255, 255, 255))
                yield viz

    imgviz.io.pyglet_imshow(images())
    imgviz.io.pyglet_run()