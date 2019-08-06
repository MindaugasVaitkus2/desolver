"""
The MIT License (MIT)

Copyright (c) 2019 Microno95, Ekin Ozturk

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

from .. import backend as D
from .. import utilities as deutil

class IntegratorTemplate(object):
    def __init__(self):
        raise NotImplementedError("Do not initialise this class directly!")

    def forward(self):
        raise NotImplementedError("Do not use this class directly! How did you initialise it??")

    __call__ = forward

    def get_aux_array(self, current_state):
        return D.stack([D.zeros_like(current_state) for i in range(self.num_stages)])

class ExplicitIntegrator(IntegratorTemplate):
    tableau = None
    final_state = None
    __symplectic__ = False

    def __init__(self, sys_dim, dtype=None, rtol=None, atol=None):
        if dtype is None:
            self.tableau     = D.array(self.tableau)
            self.final_state = D.array(self.final_state)
        else:
            self.tableau     = D.to_type(self.tableau, dtype)
            self.final_state = D.to_type(self.final_state, dtype)
            
        self.dim        = sys_dim
        self.rtol       = rtol
        self.atol       = atol
        self.adaptive   = D.shape(self.final_state)[0] == 2
        self.num_stages = D.shape(self.tableau)[0]
        self.aux        = D.zeros((self.num_stages, *self.dim))
    
    def forward(self, rhs, initial_time, initial_state, constants, timestep):
        if self.tableau is None:
            raise NotImplementedError("In order to use the fixed step integrator, subclass this class and populate the butcher tableau")
        else:
            aux = self.aux

            for stage in range(self.num_stages):
                current_state = initial_state + D.einsum("n,n...->...", self.tableau[stage, 1:], aux)
                aux[stage] = rhs(initial_time  + self.tableau[stage, 0]*timestep, current_state, **constants) * timestep

            final_time  = initial_time  + timestep
            dState      = D.einsum("n,n...->...", self.final_state[0, 1:], aux)
            final_state = initial_state + dState
            
            if self.adaptive:
                final_state2 = initial_state + D.einsum("n,n...->...", self.final_state[1, 1:], aux)
                timestep, redo_step = self.update_timestep(final_state, final_state2, initial_time, timestep)
                if redo_step:
                    timestep, (final_time, final_state, dState) = self(rhs, initial_time, initial_state, constants, timestep)
            aux[:]      = 0.0
            return timestep, (final_time, final_state, dState)

    __call__ = forward

    def update_timestep(self, final_state1, final_state2, initial_time, timestep, tol=0.9):
        err_estimate = D.max(D.abs(final_state1 - final_state2))
        relerr = self.atol + self.rtol * err_estimate
        if err_estimate != 0:
            corr = timestep * tol * (relerr / err_estimate) ** (1.0 / self.num_stages)
            if corr != 0:
                timestep = corr
        if err_estimate > relerr:
            return timestep, True
        else:
            return timestep, False

class SymplecticIntegrator(IntegratorTemplate):
    tableau = None
    __symplectic__ = True

    def __init__(self, sys_dim, dtype=None, staggered_mask=None, rtol=None, atol=None):
        if staggered_mask is None:
            staggered_mask      = D.arange(sys_dim[0]//2, sys_dim[0], dtype=D.int64)
            self.staggered_mask = D.zeros(sys_dim, dtype=D.bool)
            self.staggered_mask[staggered_mask] = 1
        else:
            self.staggered_mask = D.to_type(staggered_mask, D.bool)
            
        if dtype is None:
            self.tableau     = D.array(self.tableau)
        else:
            self.tableau     = D.to_type(self.tableau, dtype)

        self.dim        = sys_dim
        self.rtol       = rtol
        self.atol       = atol
        self.adaptive   = False
        self.num_stages = D.shape(self.tableau)[0]

    def forward(self, rhs, initial_time, initial_state, constants, timestep):
        if self.tableau is None:
            raise NotImplementedError("In order to use the fixed step integrator, subclass this class and populate the butcher tableau")
        else:
            msk  = self.staggered_mask
            nmsk = D.logical_not(self.staggered_mask)

            current_time  = D.copy(initial_time)
            current_state = D.copy(initial_state)
            dState        = D.zeros_like(current_state)

            for stage in range(self.num_stages):
                aux            = rhs(current_time, initial_state + dState, **constants) * timestep
                current_time  += timestep  * self.tableau[stage, 0]
                dState[nmsk]  += aux[nmsk] * self.tableau[stage, 1]
                dState[msk]   += aux[msk]  * self.tableau[stage, 2]
                
            final_time  = current_time
            final_state = initial_state + dState
            
            return timestep, (final_time, final_state, dState)

    __call__ = forward

    def update_timestep(self, final_state1, final_state2, initial_time, timestep, tol=0.9):
        err_estimate = D.abs(D.abs(final_state1 - final_state2))
        relerr = self.atol + self.rtol * err_estimate
        if err_estimate != 0:
            corr = timestep * tol * (relerr / err_estimate) ** (1.0 / self.num_stages)
            if corr != 0:
                timestep = corr
        if err_estimate > relerr:
            return timestep, True
        else:
            return timestep, False
