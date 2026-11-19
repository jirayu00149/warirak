CREATE TABLE `camera_frames` (
	`owner_id` text NOT NULL,
	`device_id` text NOT NULL,
	`frame_id` text NOT NULL,
	`captured_at_ms` integer NOT NULL,
	`received_at_ms` integer NOT NULL,
	`width` integer NOT NULL,
	`height` integer NOT NULL,
	`jpeg` blob NOT NULL,
	`fingerprint` text NOT NULL,
	PRIMARY KEY(`owner_id`, `device_id`)
);
--> statement-breakpoint
CREATE TABLE `workspace_invitations` (
	`owner_id` text NOT NULL,
	`id` text NOT NULL,
	`token_hash` text NOT NULL,
	`expires_at_ms` integer NOT NULL,
	`used_by` text,
	`used_at_ms` integer,
	PRIMARY KEY(`owner_id`, `id`)
);
--> statement-breakpoint
CREATE UNIQUE INDEX `invitation_hash` ON `workspace_invitations` (`token_hash`);--> statement-breakpoint
CREATE TABLE `workspace_members` (
	`owner_id` text NOT NULL,
	`user_id` text NOT NULL,
	`display_name` text NOT NULL,
	`role` text NOT NULL,
	`active` integer DEFAULT 1 NOT NULL,
	`joined_at_ms` integer NOT NULL,
	PRIMARY KEY(`owner_id`, `user_id`)
);
