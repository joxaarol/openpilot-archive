from selfdrive.controls.lib.pid import PIController
from selfdrive.controls.lib.drive_helpers import get_steer_max
from cereal import car
from cereal import log
import os
import math
import time
import numpy as np
from selfdrive.smart_torque.smart_torque_model import predict


class LatControlPID():
  def __init__(self, CP):
    self.pid = PIController((CP.lateralTuning.pid.kpBP, CP.lateralTuning.pid.kpV),
                            (CP.lateralTuning.pid.kiBP, CP.lateralTuning.pid.kiV),
                            k_f=CP.lateralTuning.pid.kf, pos_limit=1.0, sat_limit=CP.steerLimitTimer)
    self.angle_steers_des = 0.

    self.smart_torque_file = '/data/smart_torque_data'
    if not os.path.exists(self.smart_torque_file):
      with open(self.smart_torque_file, 'w') as f:
        f.write('{}\n'.format(['delta_desired',
                               'rate_desired',
                               'driver_torque',
                               'eps_torque',
                               'angle_steers',
                               'angle_steers_rate',
                               'v_ego',
                               'time']))
    self.last_pred_time = 0
    self.last_pred = 0
    self.data = []
    self.scales = {'delta_desired': [-58.75222851843965, 38.45948040492657],
                   'rate_desired': [-0.07444784045219421, 0.032148655503988266], 'driver_torque': [-286.0, 277.0],
                   'eps_torque': [-487.0, 471.0], 'angle_steers': [-47.70000076293945, 37.599998474121094],
                   'angle_steers_rate': [-41.0, 41.0], 'v_ego': [0.7249727845191956, 27.42662811279297]}

  def reset(self):
    self.pid.reset()

  def update(self, active, v_ego, angle_steers, angle_steers_rate, eps_torque, steer_override, rate_limited, CP, path_plan, CS):
    pid_log = log.ControlsState.LateralPIDState.new_message()
    pid_log.steerAngle = float(angle_steers)
    pid_log.steerRate = float(angle_steers_rate)

    if v_ego < 0.3 or not active:
      output_steer = 0.0
      pid_log.active = False
      self.pid.reset()
    else:
      self.angle_steers_des = path_plan.angleSteers  # get from MPC/PathPlanner

      self.data.append([math.degrees(path_plan.deltaDesired * 17.8),
                        math.degrees(path_plan.rateDesired * 17.8),
                        angle_steers,
                        angle_steers_rate,
                        v_ego])

      if len(self.data) == 50:
        if time.time() - self.last_pred_time > 1 / 10:
          pred = predict(np.array(self.data, dtype=np.float32))[0]
          pred = np.interp(np.interp(pred, [0, 1], self.scales['eps_torque']), [-1500, 1500], [-1, 1])
          self.last_pred = float(pred)
        del self.data[0]
        return self.last_pred

      # if CS.cruiseState.enabled:
      #   with open(self.smart_torque_file, 'a') as f:
      #     f.write('{}\n'.format([path_plan.deltaDesired,
      #                            path_plan.rateDesired,
      #                            CS.steeringTorque,
      #                            eps_torque,
      #                            angle_steers,
      #                            angle_steers_rate,
      #
      #                            v_ego,
      #                            time.time()]))

      steers_max = get_steer_max(CP, v_ego)
      self.pid.pos_limit = steers_max
      self.pid.neg_limit = -steers_max
      steer_feedforward = self.angle_steers_des   # feedforward desired angle
      if CP.steerControlType == car.CarParams.SteerControlType.torque:
        # TODO: feedforward something based on path_plan.rateSteers
        steer_feedforward -= path_plan.angleOffset   # subtract the offset, since it does not contribute to resistive torque
        steer_feedforward *= v_ego**2  # proportional to realigning tire momentum (~ lateral accel)
      deadzone = 0.0

      check_saturation = (v_ego > 10) and not rate_limited and not steer_override
      output_steer = self.pid.update(self.angle_steers_des, angle_steers, check_saturation=check_saturation, override=steer_override,
                                     feedforward=steer_feedforward, speed=v_ego, deadzone=deadzone)
      pid_log.active = True
      pid_log.p = self.pid.p
      pid_log.i = self.pid.i
      pid_log.f = self.pid.f
      pid_log.output = output_steer
      pid_log.saturated = bool(self.pid.saturated)

    return output_steer, float(self.angle_steers_des), pid_log
