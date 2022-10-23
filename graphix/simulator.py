"""MBQC simulator

Simulates MBQC by executing the pattern.

"""

import numpy as np
import qiskit.quantum_info as qi
from graphix.ops import Ops
from graphix.clifford import CLIFFORD_MEASURE, CLIFFORD


class PatternSimulator():
    """MBQC simulator

    Executes the pattern (graphix.Pattern)

    Attributes:
    -----------
    pattern : graphix.Pattern
        MBQC command sequence to be simulated
    backend : 'statevector'
        optional argument to select backend of simulation.
    results : dict
        measurement results for each measuring nodes in the graph state
    node_index : list
        the mapping of node indices to qubit indices in statevector.
    """

    def __init__(self, pattern, backend='statevector'):
        """
        Parameteres:
        --------
        pattern: graphq.pattern.Pattern object
            MBQC pattern to be simulated.
        backend: 'statevector'
            optional argument for simulation.
        """
        # check that pattern has input and output nodes configured
        assert len(pattern.input_nodes) > 0
        assert len(pattern.output_nodes) > 0
        if not pattern.output_sorted:
            pattern.sort_output()
        self.backend = backend
        self.pattern = pattern
        self.results = pattern.results
        self.sv = qi.Statevector([])
        self.node_index = []

    def qubit_dim(self):
        """Returns the qubit number in the internal statevector
        Returns
        -------
        n_qubit : int
        """
        return len(self.sv.dims())

    def normalize_state(self):
        """Normalize the internal statevector
        """
        self.sv = self.sv/self.sv.trace()**0.5

    def set_state(self, statevector):
        """Initialize the inpute state with user-specified statevector.
        Parameters
        ----------
        statevector : qiskit.quantum_info.Statevector object
            initial state for MBQC.
        """
        assert len(statevector.dims()) == len(self.pattern.input_nodes)
        self.sv = statevector
        self.node_index.extend([i for i in range(self.qubit_dim())])

    def initialize_statevector(self):
        """Initialize the internal statevector with
        tensor product of |+> state.
        """
        n = len(self.pattern.input_nodes)
        self.sv = qi.Statevector([1 for i in range(2**n)])
        self.normalize_state()
        self.node_index.extend([i for i in range(n)])

    def add_nodes(self, nodes):
        """add new qubit to internal statevector
        and assign the corresponding node number
        to list self.node_index.
        Parameters
        ---------
        nodes : list of node indices
        """
        if not self.sv:
            self.sv = qi.Statevector([1])
        n = len(nodes)
        sv_to_add = qi.Statevector([1 for i in range(2**n)])
        sv_to_add = sv_to_add/sv_to_add.trace()**0.5
        self.sv = self.sv.expand(sv_to_add)
        self.node_index.extend(nodes)

    def entangle_nodes(self, edge):
        """ Apply CZ gate to two connected nodes
        Parameters
        ----------
        edge : tuple (i, j)
            a pair of node indices
        """
        target = self.node_index.index(edge[0])
        control = self.node_index.index(edge[1])
        self.sv = self.sv.evolve(Ops.cz, [control, target])

    def measure(self, cmd):
        """Perform measurement of a node in the internal statevector and trace out the qubit
        Parameters
        ----------
        cmd : list
            measurement command : ['M', node, plane angle, s_domain, t_domain]
        """
        # choose the measurement result randomly
        result = np.random.choice([0, 1])
        self.results[cmd[1]] = result

        # extract signals for adaptive angle
        s_signal = np.sum([self.results[j] for j in cmd[4]])
        t_signal = np.sum([self.results[j] for j in cmd[5]])
        angle = cmd[3] * np.pi * (-1)**s_signal + np.pi * t_signal
        meas_op = self.meas_op(angle, 0, plane=cmd[2], choice=result)
        loc = self.node_index.index(cmd[1])
        # perform measurement
        self.sv = self.sv.evolve(meas_op, [loc])

        # trace out measured qubit
        self.normalize_state()
        state_dm = qi.partial_trace(self.sv, [loc])
        self.sv = state_dm.to_statevector()

        # update node_index
        self.node_index.remove(cmd[1])

    def correct_byproduct(self, cmd):
        """Byproduct correction
        correct for the X or Z byproduct operators,
        by applying the X or Z gate.
        """
        if np.mod(np.sum([self.results[j] for j in cmd[2]]), 2) == 1:
            loc = self.node_index.index(cmd[1])
            if cmd[0] == 'X':
                op = Ops.x
            elif cmd[0] == 'Z':
                op = Ops.z
            self.sv = self.sv.evolve(op, [loc])

    def run(self):
        self.initialize_statevector()
        for cmd in self.pattern.seq:
            if cmd[0] == 'N':
                self.add_nodes([cmd[1]])
            elif cmd[0] == 'E':
                self.entangle_nodes(cmd[1])
            elif cmd[0] == 'M':
                self.measure(cmd)
            elif cmd[0] == 'X':
                self.correct_byproduct(cmd)
            elif cmd[0] == 'Z':
                self.correct_byproduct(cmd)
            else:
                raise ValueError("invalid commands")

    @staticmethod
    def meas_op(angle, vop, plane='XY', choice=0):
        """Returns the projection operator for given measurement angle and local Clifford op (VOP).

        Parameters
        ----------
        angle: float
            original measurement angle in radian
        vop : int
            index of local Clifford (vop), see graphq.clifford.CLIFFORD
        plane : 'XY', 'YZ' or 'ZX'
            measurement plane on which angle shall be defined
        choice : 0 or 1
            choice of measurement outcome. measured eigenvalue would be (-1)**choice.

        Returns
        -------
        op : qi.Operator
            projection operator

        """
        assert vop in np.arange(24)
        assert choice in [0, 1]
        assert plane in ['XY', 'YZ', 'ZX']
        if plane == 'XY':
            vec = (np.cos(angle), np.sin(angle), 0)
        elif plane == 'YZ':
            vec = (0, np.cos(angle), np.sin(angle))
        elif plane == 'ZX':
            vec = (np.sin(angle), 0, np.sin(angle))
        op_mat = np.eye(2, dtype=np.complex128) / 2
        for i in range(3):
            op_mat += (-1)**(choice + CLIFFORD_MEASURE[vop][i][1]) \
                * vec[CLIFFORD_MEASURE[vop][i][0]] * CLIFFORD[i + 1] / 2
        return qi.Operator(op_mat)