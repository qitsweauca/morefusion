#!/usr/bin/env python

import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # NOQA
import numpy as np

from objslampp.geometry import points_from_angles


def main():
    point = points_from_angles(
        distance=[1],
        elevation=[135],
        azimuth=[45],
        is_degree=True,
    )[0]
    print(point)

    ax = plt.subplot(111, projection='3d')

    # plot unit sphere
    u, v = np.mgrid[0:2 * np.pi:20j, 0:np.pi:10j]
    x = np.cos(u) * np.sin(v)
    y = np.sin(u) * np.sin(v)
    z = np.cos(v)
    ax.plot_wireframe(x, y, z, color='r')

    # plot point
    xs = [0, point[0]]
    ys = [0, point[1]]
    zs = [0, point[2]]
    ax.plot(xs, ys, zs, marker='o', color='b')
    ax.set_xlim(-1, 1)
    ax.set_ylim(-1, 1)
    ax.set_zlim(-1, 1)
    plt.show()


if __name__ == '__main__':
    main()