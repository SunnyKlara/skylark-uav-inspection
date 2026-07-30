from setuptools import find_packages, setup

package_name = 'skylark_autopilot_iface'

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
    description='把 PX4 飞控包装成 Skylark 的飞行动作抽象',
    license='AGPL-3.0-or-later',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            # 单一节点：同时承担 FlightHealth 发布与飞行动作服务。
            # 刻意不拆成多个节点 —— offboard setpoint 流必须只有一个发布者，
            # 拆开会出现两个节点同时发 setpoint 互相打断。
            'autopilot_iface = skylark_autopilot_iface.autopilot_iface_node:main',
            # 测试用客户端，给集成测试和手工验证用
            'takeoff_cli = skylark_autopilot_iface.takeoff_cli:main',
        ],
    },
)
