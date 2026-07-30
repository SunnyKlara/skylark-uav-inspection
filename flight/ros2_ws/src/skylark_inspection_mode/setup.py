from setuptools import find_packages, setup

package_name = 'skylark_inspection_mode'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Skylark Window-E',
    maintainer_email='klara@example.invalid',
    description='flight 层任务状态机：扫掠与降高复拍',
    license='AGPL-3.0-or-later',
    entry_points={
        'console_scripts': [
            # 节点尚未实现，先只交付纯函数几何模块（geometry.py）与它的单测。
            # 刻意分两步：几何是覆盖率保证的根，先把它钉死再接 ROS，
            # 否则单测就得拖着 rclpy 跑，碎片时间推不动。
        ],
    },
)
