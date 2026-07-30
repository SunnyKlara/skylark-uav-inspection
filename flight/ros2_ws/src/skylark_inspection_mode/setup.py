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
            # 任务状态机。当前只注册 inspect_sweep 一个 action；
            # Revisit 未实现时**刻意不注册桩**，让调用方直接看到"服务器不在线"
            # 而不是拿到一个语义不明的失败码。
            'inspection_mode = skylark_inspection_mode.inspection_mode_node:main',
            # 测试用客户端。退出码即 result_code，输出是 key=value ——
            # 集成测试不必解析 YAML，取消也走显式 cancel_goal_async 而不是
            # 指望 CLI 的信号处理（实测那条路在 InspectSweep 上不生效）。
            'sweep_cli = skylark_inspection_mode.sweep_cli:main',
        ],
    },
)
