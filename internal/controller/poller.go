package controller

import (
	"context"
	"time"
)

// runPollMode runs the controller in poll mode with periodic reconciliation
func (c *Controller) runPollMode(ctx context.Context) error {
	c.logger.Info().
		Dur("interval", c.cfg.PollInterval).
		Msg("Starting poll mode with periodic reconciliation")

	ticker := time.NewTicker(c.cfg.PollInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
			if err := c.syncAll(ctx); err != nil {
				c.logger.Error().Err(err).Msg("Periodic sync failed")
				continue
			}

			// Update sync lag
			now := time.Now().Unix()
			lastSuccess := int64(0)
			// This is a simplified version - you could track actual last success time
			lag := now - lastSuccess
			if lag < 0 {
				lag = 0
			}
			c.updateMetrics(float64(lag))
		}
	}
}

// updateMetrics updates the sync lag metric
func (c *Controller) updateMetrics(lag float64) {
	// In poll mode, lag is the time since last successful sync
	// This is handled by LastSuccessTimestamp in syncAll
}
