CREATE TABLE `collection_events` (
	`owner_id` text NOT NULL,
	`id` text NOT NULL,
	`mission_id` text NOT NULL,
	`source` text NOT NULL,
	`device_id` text,
	`class_id` integer,
	`occurred_at_ms` integer NOT NULL,
	`received_at_ms` integer NOT NULL,
	`estimated` integer DEFAULT 0 NOT NULL,
	`fingerprint` text NOT NULL,
	PRIMARY KEY(`owner_id`, `id`)
);
--> statement-breakpoint
CREATE INDEX `collection_owner_date` ON `collection_events` (`owner_id`,`source`,`occurred_at_ms`);--> statement-breakpoint
CREATE TABLE `devices` (
	`owner_id` text NOT NULL,
	`id` text NOT NULL,
	`name` text NOT NULL,
	`token_hash` text NOT NULL,
	`created_at_ms` integer NOT NULL,
	`revoked_at_ms` integer,
	PRIMARY KEY(`owner_id`, `id`)
);
--> statement-breakpoint
CREATE UNIQUE INDEX `device_token_hash` ON `devices` (`token_hash`);--> statement-breakpoint
CREATE TABLE `missions` (
	`owner_id` text NOT NULL,
	`id` text NOT NULL,
	`source` text NOT NULL,
	`device_id` text,
	`scenario` text NOT NULL,
	`state` text NOT NULL,
	`started_at_ms` integer NOT NULL,
	`updated_at_ms` integer NOT NULL,
	`received_at_ms` integer NOT NULL,
	`elapsed_s` integer NOT NULL,
	`detected_count` integer NOT NULL,
	PRIMARY KEY(`owner_id`, `id`)
);
--> statement-breakpoint
CREATE INDEX `mission_owner_time` ON `missions` (`owner_id`,`started_at_ms`);--> statement-breakpoint
CREATE TABLE `device_telemetry` (
	`owner_id` text NOT NULL,
	`device_id` text NOT NULL,
	`observed_at_ms` integer NOT NULL,
	`received_at_ms` integer NOT NULL,
	`battery_percent` real NOT NULL,
	`state` text NOT NULL,
	PRIMARY KEY(`owner_id`, `device_id`)
);
