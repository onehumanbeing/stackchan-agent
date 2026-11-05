"""Smoke tests: python3 -m unittest discover sim"""

import unittest

import preview
import run
import shortarm as S
from shortarm import dance


class ShortArm(unittest.TestCase):
    def test_arm_directions(self):
        pivot_y = S.PITCH_Y + S.SHOULDER[1]
        down, fwd = S.tip({"l": 0}, "l"), S.tip({"l": 90}, "l")
        self.assertLess(down[1], pivot_y)                       # 0 = hanging down
        self.assertGreater(fwd[2], 30)                          # 90 = forward
        self.assertGreater(S.tip({"l": 0}, "l")[0], 0)          # left arm on +x
        self.assertLess(S.tip({"r": 0}, "r")[0], 0)

    def test_head_moves_arms(self):
        self.assertGreater(S.tip({"l": 90, "pitch": 18}, "l")[1], S.tip({"l": 90}, "l")[1])   # pitch up lifts the arm
        self.assertGreater(S.tip({"l": 90, "yaw": 28}, "l")[0], S.tip({"l": 90}, "l")[0])     # yaw left turns it left

    def test_servo_goal_matches_dance(self):
        d = dance.Dance(robot=None, calibration=S.CALIBRATION)
        for key, v in (("l", 60), ("r", 30), ("yaw", 10), ("pitch", -5)):
            self.assertAlmostEqual(S.servo_goal(key, v), d._command(key, v, 0.5, 0)[1]["deg"], places=6)

    def test_neutral_is_fine(self):
        self.assertEqual(S.check_pose({})["problems"], [])

    def test_move_profile(self):
        for delta, speed in ((5, 3200), (30, 1000), (100, 3200)):
            t = S.arm_move_time(delta, speed, dance.ARM_ACC)
            self.assertAlmostEqual(S.arm_position(0, delta, t, speed, dance.ARM_ACC), delta, places=6)
            self.assertLess(S.arm_position(0, delta, t / 2, speed, dance.ARM_ACC), delta)

    def test_tools_run(self):
        self.assertIn("moves", run.dance_report(0.5))
        self.assertGreater(run.sweep(25, 100)["poses"], 0)
        self.assertIn("<svg", preview.pose_svg({"l": 50}))


if __name__ == "__main__":
    unittest.main()
